REGION_TZ = {
    # UTC+2
    "калининград": "Europe/Kaliningrad",

    # UTC+3 MSK
    "москва": "Europe/Moscow",
    "московская": "Europe/Moscow",
    "санкт-петербург": "Europe/Moscow",
    "ленинградская": "Europe/Moscow",
    "нижегород": "Europe/Moscow",
    "нижний новгород": "Europe/Moscow",
    "татарстан": "Europe/Moscow",
    "казань": "Europe/Moscow",
    "краснодар": "Europe/Moscow",
    "ростов": "Europe/Moscow",
    "воронеж": "Europe/Moscow",
    "волгоград": "Europe/Volgograd",
    "саратов": "Europe/Saratov",
    "крым": "Europe/Moscow",
    "севастополь": "Europe/Moscow",
    "дагестан": "Europe/Moscow",
    "чечен": "Europe/Moscow",
    "ставрополь": "Europe/Moscow",
    "ярослав": "Europe/Moscow",
    "твер": "Europe/Moscow",
    "тула": "Europe/Moscow",
    "рязан": "Europe/Moscow",
    "смоленск": "Europe/Moscow",
    "брянск": "Europe/Moscow",
    "орёл": "Europe/Moscow",
    "орел": "Europe/Moscow",
    "курск": "Europe/Moscow",
    "липецк": "Europe/Moscow",
    "тамбов": "Europe/Moscow",
    "белгород": "Europe/Moscow",
    "иванов": "Europe/Moscow",
    "владимир": "Europe/Moscow",
    "калуга": "Europe/Moscow",
    "костром": "Europe/Moscow",
    "новгородская": "Europe/Moscow",
    "псков": "Europe/Moscow",
    "карелия": "Europe/Moscow",
    "коми": "Europe/Moscow",
    "архангельск": "Europe/Moscow",
    "мурманск": "Europe/Moscow",
    "ненец": "Europe/Moscow",
    "марий эл": "Europe/Moscow",
    "мордов": "Europe/Moscow",
    "чуваш": "Europe/Moscow",
    "пенза": "Europe/Moscow",
    "киров": "Europe/Kirov",

    # UTC+4
    "самара": "Europe/Samara",
    "самарская": "Europe/Samara",
    "удмурт": "Europe/Samara",
    "ижевск": "Europe/Samara",
    "ульяновск": "Europe/Ulyanovsk",
    "астрахан": "Europe/Astrakhan",

    # UTC+5
    "башкир": "Asia/Yekaterinburg",
    "уфа": "Asia/Yekaterinburg",
    "перм": "Asia/Yekaterinburg",
    "екатеринбург": "Asia/Yekaterinburg",
    "свердлов": "Asia/Yekaterinburg",
    "челябинск": "Asia/Yekaterinburg",
    "тюмень": "Asia/Yekaterinburg",
    "курган": "Asia/Yekaterinburg",
    "оренбург": "Asia/Yekaterinburg",
    "ханты": "Asia/Yekaterinburg",
    "хмао": "Asia/Yekaterinburg",
    "ямал": "Asia/Yekaterinburg",
    "янао": "Asia/Yekaterinburg",

    # UTC+6
    "омск": "Asia/Omsk",

    # UTC+7
    "новосибирск": "Asia/Novosibirsk",
    "томск": "Asia/Tomsk",
    "кемеров": "Asia/Novokuznetsk",
    "алтайский край": "Asia/Barnaul",
    "республика алтай": "Asia/Barnaul",
    "барнаул": "Asia/Barnaul",
    "красноярск": "Asia/Krasnoyarsk",
    "хакасия": "Asia/Krasnoyarsk",
    "тыва": "Asia/Krasnoyarsk",
    "тува": "Asia/Krasnoyarsk",

    # UTC+8
    "иркутск": "Asia/Irkutsk",
    "бурят": "Asia/Irkutsk",
    "забайкаль": "Asia/Chita",
    "чита": "Asia/Chita",

    # UTC+9
    "якут": "Asia/Yakutsk",
    "амур": "Asia/Yakutsk",
    "благовещенск": "Asia/Yakutsk",

    # UTC+10
    "владивосток": "Asia/Vladivostok",
    "примор": "Asia/Vladivostok",
    "хабаровск": "Asia/Vladivostok",
    "еврейская автономная": "Asia/Vladivostok",

    # UTC+11
    "магадан": "Asia/Magadan",
    "сахалин": "Asia/Sakhalin",

    # UTC+12
    "камчат": "Asia/Kamchatka",
    "чукот": "Asia/Anadyr",
    "анадыр": "Asia/Anadyr",
}


def resolve_timezone(region: str | None) -> str:
    if not region:
        return "Europe/Moscow"

    r = region.lower().replace("ё", "е")

    for key, tz in REGION_TZ.items():
        if key in r:
            return tz

    return "Europe/Moscow"
