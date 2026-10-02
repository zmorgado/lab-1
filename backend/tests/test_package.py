import snippet_search


def test_package_is_importable() -> None:
    # Smoke test del cableado: el import de arriba es la prueba real — si el
    # src layout no quedo instalado, revienta antes de llegar a este assert.
    assert snippet_search.__name__ == "snippet_search"
