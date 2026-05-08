from core import parser
from gtool import print_phone_normalization


def test_print_phone_b_normalization(capsys):
    ctx = parser.parse("Номер принимающего звонок (Б): 83912777454")

    print_phone_normalization(ctx)

    assert "Номер Б нормализован: 83912777454 -> 73912777454" in capsys.readouterr().out
