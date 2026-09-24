from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from enum import Enum
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, status
from pydantic import BaseModel, EmailStr, Field

# Prestamo por defecto: dos semanas, como cualquier biblioteca.
DEFAULT_LOAN_DAYS = 14
MAX_ACTIVE_RESERVATIONS = 3


class ReservationStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    RETURNED = "returned"
    CANCELLED = "cancelled"


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    email: EmailStr


class User(UserCreate):
    id: UUID
    joined_on: date


class BookCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    author: str
    isbn: str = Field(pattern=r"^\d{10}(\d{3})?$")


class Book(BookCreate):
    id: UUID
    owner_id: UUID
    available: bool = True


class Reservation(BaseModel):
    id: UUID
    book_id: UUID
    borrower_id: UUID
    status: ReservationStatus
    reserved_on: date
    due_on: date


class InMemoryRepository:
    """Persistencia de mentira: diccionarios en memoria, sin base de datos.

    Alcanza para el mock. Un repo real cambiaria esto por SQLAlchemy sin tocar
    las rutas, que es justamente el punto de inyectarlo con Depends.
    """

    def __init__(self) -> None:
        self.users: dict[UUID, User] = {}
        self.books: dict[UUID, Book] = {}
        self.reservations: dict[UUID, Reservation] = {}
        # Indice inverso para contar reservas activas sin recorrer todo.
        self.by_borrower: dict[UUID, list[UUID]] = defaultdict(list)

    def active_reservations(self, borrower_id: UUID) -> list[Reservation]:
        return [
            self.reservations[rid]
            for rid in self.by_borrower[borrower_id]
            if self.reservations[rid].status == ReservationStatus.ACTIVE
        ]


repository = InMemoryRepository()


def get_repository() -> InMemoryRepository:
    return repository


def get_current_user(
    user_id: UUID = Query(..., description="Caller identity, stubbed for the mock"),
    repo: InMemoryRepository = Depends(get_repository),
) -> User:
    """Auth de mentira: el caller manda su id por query string.

    En produccion esto seria un bearer token; para el mock solo hace falta que
    las rutas reciban un User y puedan comparar ownership.
    """
    user = repo.users.get(user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown user"
        )
    return user


router = APIRouter(prefix="/api/v1", tags=["lending"])


@router.post("/users", response_model=User, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate, repo: InMemoryRepository = Depends(get_repository)
) -> User:
    if any(u.username == payload.username for u in repo.users.values()):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Username already taken"
        )

    user = User(id=uuid4(), joined_on=date.today(), **payload.model_dump())
    repo.users[user.id] = user
    return user


@router.post("/books", response_model=Book, status_code=status.HTTP_201_CREATED)
def create_book(
    payload: BookCreate,
    current_user: User = Depends(get_current_user),
    repo: InMemoryRepository = Depends(get_repository),
) -> Book:
    """Registra un libro a nombre de quien llama: el dueño no se pide, se toma."""
    if any(b.isbn == payload.isbn for b in repo.books.values()):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Book already registered"
        )

    book = Book(id=uuid4(), owner_id=current_user.id, **payload.model_dump())
    repo.books[book.id] = book
    return book


@router.get("/books", response_model=list[Book])
def list_books(
    available_only: bool = True,
    author: str | None = None,
    repo: InMemoryRepository = Depends(get_repository),
) -> list[Book]:
    books = list(repo.books.values())
    if available_only:
        books = [b for b in books if b.available]
    if author:
        needle = author.casefold()
        books = [b for b in books if needle in b.author.casefold()]
    return sorted(books, key=lambda b: b.title)


@router.post(
    "/reservations", response_model=Reservation, status_code=status.HTTP_201_CREATED
)
def reserve_book(
    book_id: UUID,
    current_user: User = Depends(get_current_user),
    repo: InMemoryRepository = Depends(get_repository),
) -> Reservation:
    """Reserva el libro de otra persona.

    Tres reglas, en orden de lo barato a lo caro de verificar: que el libro
    exista, que no sea propio, y que el usuario no haya llegado al tope de
    reservas activas.
    """
    book = repo.books.get(book_id)
    if book is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Book not found"
        )
    if book.owner_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot reserve your own book",
        )
    if not book.available:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Book is already lent out"
        )
    if len(repo.active_reservations(current_user.id)) >= MAX_ACTIVE_RESERVATIONS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Limit of {MAX_ACTIVE_RESERVATIONS} active reservations reached",
        )

    today = date.today()
    reservation = Reservation(
        id=uuid4(),
        book_id=book.id,
        borrower_id=current_user.id,
        status=ReservationStatus.ACTIVE,
        reserved_on=today,
        due_on=today + timedelta(days=DEFAULT_LOAN_DAYS),
    )

    book.available = False
    repo.reservations[reservation.id] = reservation
    repo.by_borrower[current_user.id].append(reservation.id)
    return reservation


@router.post("/reservations/{reservation_id}/return", response_model=Reservation)
def return_book(
    reservation_id: UUID,
    current_user: User = Depends(get_current_user),
    repo: InMemoryRepository = Depends(get_repository),
) -> Reservation:
    reservation = repo.reservations.get(reservation_id)
    if reservation is None or reservation.borrower_id != current_user.id:
        # Mismo 404 para "no existe" y "no es tuya": no filtra la existencia
        # de reservas ajenas a quien anda probando ids.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Reservation not found"
        )
    if reservation.status != ReservationStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Reservation is not active"
        )

    reservation.status = ReservationStatus.RETURNED
    repo.books[reservation.book_id].available = True
    return reservation


app = FastAPI(title="Book Lending Platform", version="0.1.0")
app.include_router(router)
