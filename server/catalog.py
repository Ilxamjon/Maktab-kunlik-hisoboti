# Stable IDs. Do not reorder: saved reports contain these IDs.
REASONS = [
    'Kelgan',
    'Kasalligi tufayli',
    'Oilaviy tadbir uchun ruxsat olgan',
    'Tanlov yoki musobaqada qatnashmoqda',
    'Sababsiz dars qoldiradi',
    'Boshqa sabablar',
    'Ijtimoiy ahvoli og‘irligi sababli',
    'Surunkali dars qoldirayotgan',
    'Qidiruvda bo‘lgan oila farzandi',
    'Chet elga ruxsatsiz chiqib ketgan',
    'Ta’limdan bo‘yin tovlagan',
    'Darsga kelmasdan ishlab yurgan',
    'Ta’lim olishiga ota-onasi qarshi',
    'Jazoni o‘tash muassasasida yoki tergovda',
    'Diniy libos bilan bog‘liq sabab',
    'Ota-ona nazoratsizligi',
    'Oilaviy sharoitiga ko‘ra (sababsiz)',
    'Turmushga chiqqanligi tufayli',
]
EXCUSED = (1, 3, 2, 6, 5)
UNEXCUSED = (7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 4, 17)
COLUMN_ORDER = EXCUSED + UNEXCUSED
