"""Test de humo: los paquetes del proyecto se importan sin errores."""


def test_paquetes_importan():
    import dashboard  # noqa: F401
    import datos  # noqa: F401
    import ingesta  # noqa: F401
