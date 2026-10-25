"""Автокернер (Autokerner): расчёт полей знаков, пробела и кернинга
(классы и пары) по всем мастерам шрифта.

Расчёт — на чистом Python, без FontLab: `model` описывает шрифт,
`auto.run` считает. Обёртка для FontLab 8 — `fontlab_bridge`.
"""

__version__ = "0.5.1"
__copyright__ = "Copyright © 2026 Sasha Pavljenko"
__license__ = "MIT"

# Автор: почта для сообщений об ошибках, сайт, страница добровольной поддержки
# (страница скрипта на сайте: кнопки «Поддержать» и «Скачать»)
EMAIL = "pavljenko@ya.ru"
SITE_URL = "https://pavljenko.ru"
SUPPORT_URL = "https://pavljenko.ru/product/autokerner"
