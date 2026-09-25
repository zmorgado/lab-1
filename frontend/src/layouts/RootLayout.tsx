import { Outlet, useLocation } from "react-router"
import { ToastContainer } from "react-toastify"
import "react-toastify/dist/ReactToastify.css"
import Header from "@/components/Header"
import Footer from "@/components/Footer"

export default function RootLayout() {
  const location = useLocation()
  const hideFooter = location.pathname === "/search" || location.pathname === "/contact"

  return (
    <div className="flex min-h-screen flex-col">
      <ToastContainer position="bottom-right" autoClose={4000} />
      <Header />
      <main className="flex-1 flex flex-col">
        <Outlet />
      </main>
      {!hideFooter && <Footer />}
    </div>
  )
}
