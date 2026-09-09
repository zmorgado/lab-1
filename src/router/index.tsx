import { createBrowserRouter } from "react-router"
import RootLayout from "@/layouts/RootLayout"
import NotFound from "@/pages/NotFound"
import Home from "@/pages/Home"
import Search from "@/pages/Search"
import Contact from "@/pages/Contact"
import AboutUs from "@/pages/AboutUs"

export const router = createBrowserRouter([
  {
    path: "/",
    element: <RootLayout />,
    errorElement: <NotFound />,
    children: [
      { path: "/", element: <Home /> },
      { path: "/search", element: <Search />},
      { path: "/contact", element: <Contact />},
      { path: "/about-us", element: <AboutUs />}
    ],
  }
])
