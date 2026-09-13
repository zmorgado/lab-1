import HomeOptionButton from "@/components/HomeOptionButton"

export default function Home() {
  return (
    <section className="flex flex-col pt-20 items-center">
      <h1 className="text-4xl font-bold italic pb-20"> REPOSITORY FINDER </h1>
      <article className="px-2">
        Lorem ipsum dolor sit amet consectetur adipisicing elit. Non nobis rem magni rerum aperiam unde, iste 
        asperiores eligendi id voluptatum accusantium excepturi at autem optio repellendus facere in aliquam esse.
        Lorem ipsum dolor sit amet consectetur adipisicing elit. Non nobis rem magni rerum aperiam unde, iste 
        asperiores eligendi id voluptatum accusantium excepturi at autem optio repellendus facere in aliquam esse.
        Lorem ipsum dolor sit amet consectetur adipisicing elit. Non nobis rem magni rerum aperiam unde, iste 
        asperiores eligendi id voluptatum accusantium excepturi at autem optio repellendus facere in aliquam esse.
      </article>

      <section className="flex gap-10 mt-20 p-3">
        <HomeOptionButton text="Search a repo" redirectTo="/search"/>
        <HomeOptionButton text="Contact another developers" redirectTo="/contact"/>
      </section>
    </section>
  )
}