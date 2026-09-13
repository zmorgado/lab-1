import code_search_proxy


def test_package_is_importable() -> None:
    # Smoke test del cableado: el import de arriba es la prueba real — si el
    # src layout no quedo instalado, revienta antes de llegar a este assert.
    assert code_search_proxy.__name__ == "code_search_proxy"
