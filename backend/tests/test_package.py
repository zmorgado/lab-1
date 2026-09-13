import code_search_proxy


def test_package_is_importable() -> None:
    # Cablea el runner de punta a punta: si el src layout no quedo instalado,
    # el import de arriba revienta antes de llegar a este assert.
    assert code_search_proxy.__name__ == "code_search_proxy"
