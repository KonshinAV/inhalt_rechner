#!/usr/bin/env python3
"""
Расчёт дохода в Германии (brutto / netto) по часовой ставке.

Параметры читаются из файла config.yml,
Расчёт приблизительный.

"""

import math
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("Не установлена библиотека PyYAML. Установите: pip install pyyaml")

# Путь к файлу настроек: лежит в той же папке, что и этот скрипт
CONFIG_FILE = Path(__file__).resolve().parent / "config.yml"

# ---------------------------------------------------------------- Параметры 2026 года

# Налог на доход (Einkommensteuer)
GRUNDFREIBETRAG = 12_348          # Необлагаемый минимум в год
WERBUNGSKOSTEN_PAUSCHALE = 1_230  # Паушальный вычет профессиональных расходов
SONDERAUSGABEN_PAUSCHALE = 36     # Паушальный вычет специальных расходов

# Потолки, выше которых взносы не начисляются (в год)
BBG_RV_ALV = 101_400  # Для пенсионного страхования и страхования от безработицы
BBG_KV_PV = 69_750    # Для медицинского и страхования по уходу

# Доля работника в социальных взносах
RV_EMPLOYEE = 0.093             # Rentenversicherung (пенсионное), 9,3 %
ALV_EMPLOYEE = 0.013            # Arbeitslosenversicherung (от безработицы), 1,3 %
KV_EMPLOYEE_BASE = 0.073        # Krankenversicherung (медицинское), 7,3 % без Zusatzbeitrag
PV_EMPLOYEE_BASE = 0.018        # Pflegeversicherung (по уходу), 1,8 %
PV_CHILDLESS_SURCHARGE = 0.006  # Доплата к Pflegeversicherung для бездетных
PV_DISCOUNT_PER_CHILD = 0.0025  # Скидка за каждого ребёнка со 2-го по 5-го

# Солидарная надбавка (Solidaritätszuschlag)
SOLI_RATE = 0.055         # Ставка 5,5 % от налога
SOLI_FREIGRENZE = 20_350  # Порог, до которого Soli не платится (для splitting удваивается)

# Граница Minijob (доход в месяц)
MINIJOB_LIMIT_MONTHLY = 603


# ---------------------------------------------------------------- Расчёт налогов

def income_tax_single(zve: float) -> float:
    """
    Подоходный налог по базовому тарифу (Grundtarif) 2026 года.
    zve — налогооблагаемый доход за год (zu versteuerndes Einkommen).
    """
    x = math.floor(zve)

    # Зона 1: доход не превышает необлагаемый минимум — налог не платится
    if x <= GRUNDFREIBETRAG:
        return 0.0

    # Зона 2: первая прогрессивная зона
    if x <= 17_799:
        y = (x - GRUNDFREIBETRAG) / 10_000
        return math.floor((914.51 * y + 1_400) * y)

    # Зона 3: вторая прогрессивная зона
    if x <= 69_878:
        z = (x - 17_799) / 10_000
        return math.floor((173.1 * z + 2_397) * z + 1_034.87)

    # Зона 4: пропорциональная ставка 42 %
    if x <= 277_825:
        return math.floor(0.42 * x - 11_135.63)

    # Зона 5: «налог для богатых», ставка 45 %
    return math.floor(0.45 * x - 19_470.38)


def income_tax(zve: float, tax_class: int) -> float:
    """Подоходный налог с учётом класса налога."""
    if tax_class == 3:
        # Класс 3 использует splitting-тариф: налог считается
        # от половины дохода и затем удваивается
        return 2 * income_tax_single(zve / 2)
    # Классы 1 и 4 — обычный базовый тариф
    return income_tax_single(zve)


def solidarity_surcharge(tax: float, tax_class: int) -> float:
    """Солидарная надбавка (Soli) с зоной плавного перехода."""
    # Для класса 3 порог освобождения удваивается
    freigrenze = SOLI_FREIGRENZE * (2 if tax_class == 3 else 1)

    # Налог ниже порога — Soli не платится
    if tax <= freigrenze:
        return 0.0

    # В зоне перехода Soli не может превышать 11,9 % от суммы превышения порога
    return min(SOLI_RATE * tax, 0.119 * (tax - freigrenze))


# ---------------------------------------------------------------- Основной расчёт

def calculate_year(gross_year: float, tax_class: int, children: int,
                   church_rate: float, kv_extra_percent: float) -> dict:
    """Рассчитывает все удержания и netto за год. Возвращает словарь с результатами."""

    # --- Социальные взносы работника ---
    # Пенсионное и страхование от безработицы (с учётом потолка)
    rv = min(gross_year, BBG_RV_ALV) * RV_EMPLOYEE
    alv = min(gross_year, BBG_RV_ALV) * ALV_EMPLOYEE

    # Медицинское: базовая ставка + половина дополнительного взноса кассы
    kv_rate = KV_EMPLOYEE_BASE + kv_extra_percent / 100 / 2
    kv = min(gross_year, BBG_KV_PV) * kv_rate

    # Страхование по уходу: зависит от количества детей
    pv_rate = PV_EMPLOYEE_BASE
    if children == 0:
        # Бездетные платят доплату
        pv_rate += PV_CHILDLESS_SURCHARGE
    elif children >= 2:
        # Скидка за детей со 2-го по 5-го (максимум 4 ребёнка в расчёте)
        pv_rate -= PV_DISCOUNT_PER_CHILD * min(children - 1, 4)
    pv = min(gross_year, BBG_KV_PV) * pv_rate

    social = rv + alv + kv + pv

    # --- Налогооблагаемый доход ---
    # Из brutto вычитаются паушальные вычеты и социальные взносы
    # (это упрощённое приближение Vorsorgepauschale)
    zve = max(0.0, gross_year
              - WERBUNGSKOSTEN_PAUSCHALE
              - SONDERAUSGABEN_PAUSCHALE
              - social)

    # --- Налоги ---
    tax = income_tax(zve, tax_class)
    soli = solidarity_surcharge(tax, tax_class)
    church = tax * church_rate  # Церковный налог — процент от подоходного налога

    # --- Итог: netto = brutto минус все удержания ---
    net = gross_year - social - tax - soli - church

    return {
        "gross": gross_year, "net": net,
        "rv": rv, "alv": alv, "kv": kv, "pv": pv,
        "tax": tax, "soli": soli, "church": church,
    }


# ---------------------------------------------------------------- Ввод и вывод

def load_config() -> dict:
    """Читает настройки из config.yml."""
    if not CONFIG_FILE.exists():
        sys.exit(f"Файл конфигурации не найден: {CONFIG_FILE}")
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        sys.exit(f"Ошибка в config.yml: {e}")

    # Пустой файл даёт None — считаем это ошибкой
    if not isinstance(data, dict):
        sys.exit("config.yml пуст или имеет неверный формат.")
    return data


def eur(value: float) -> str:
    """Форматирует число как сумму в евро: 1 234,56 €."""
    return f"{value:,.2f} €".replace(",", " ").replace(".", ",")


def main() -> None:
    cfg = load_config()

    # Обязательные параметры
    try:
        rate = float(cfg["hourly_rate"])
        hours = float(cfg["hours_per_week"])
    except KeyError as e:
        sys.exit(f"В config.yml отсутствует параметр: {e}")

    # Необязательные параметры (если не заданы — берутся значения по умолчанию)
    opt = cfg.get("optional") or {}
    tax_class = int(opt.get("tax_class", 1))
    children = int(opt.get("children", 0))
    church_rate = float(opt.get("church_tax_rate", 0.0))
    kv_extra = float(opt.get("health_insurance_extra_rate", 2.9))
    weeks = float(opt.get("weeks_per_year", 52))

    if tax_class not in (1, 3, 4):
        sys.exit("Поддерживаются только классы налогов 1, 3 и 4.")

    # Расчёт brutto: ставка × часы × недели
    gross_week = rate * hours
    gross_year = gross_week * weeks

    # Расчёт всех удержаний и netto
    r = calculate_year(gross_year, tax_class, children, church_rate, kv_extra)

    net_year = r["net"]
    ratio = net_year / gross_year if gross_year else 0

    # --- Вывод таблицы доходов ---
    print(f"\nСтавка: {eur(rate)}/час | {hours:g} ч/нед | Steuerklasse {tax_class}")
    print("=" * 52)
    print(f"{'':<12}{'Brutto':>18}{'Netto':>18}")
    print("-" * 52)
    print(f"{'В неделю':<12}{eur(gross_year / weeks):>18}{eur(net_year / weeks):>18}")
    print(f"{'В месяц':<12}{eur(gross_year / 12):>18}{eur(net_year / 12):>18}")
    print(f"{'В год':<12}{eur(gross_year):>18}{eur(net_year):>18}")
    print("=" * 52)
    print(f"Netto составляет {ratio:.1%} от brutto\n")

    # --- Вывод разбивки удержаний ---
    print("Удержания в год:")
    print(f"  Rentenversicherung        {eur(r['rv']):>14}")
    print(f"  Arbeitslosenversicherung  {eur(r['alv']):>14}")
    print(f"  Krankenversicherung       {eur(r['kv']):>14}")
    print(f"  Pflegeversicherung        {eur(r['pv']):>14}")
    print(f"  Lohnsteuer                {eur(r['tax']):>14}")
    print(f"  Solidaritätszuschlag      {eur(r['soli']):>14}")
    if church_rate:
        print(f"  Kirchensteuer             {eur(r['church']):>14}")

    # --- Предупреждения о особых режимах ---
    monthly_gross = gross_year / 12
    if monthly_gross <= MINIJOB_LIMIT_MONTHLY:
        print(f"\n⚠ Доход в месяц ≤ {MINIJOB_LIMIT_MONTHLY} € — это Minijob, "
              "расчёт неприменим (взносы платит работодатель).")
    elif monthly_gross <= 2_000:
        print("\n⚠ Доход в Übergangsbereich (Midijob) — взносы ниже, "
              "реальный netto будет немного выше расчётного.")
    print("\nРасчёт приблизительный; точные значения — в Lohnabrechnung.")


# Точка входа: запуск программы
if __name__ == "__main__":
    main()
