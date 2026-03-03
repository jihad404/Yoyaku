import time
from datetime import date
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

URL = "https://www.etermin.net/stadt-duisburg-zul"

# jQuery UI datepicker: selectable days carry class "dayA" and data-handler="selectDay"
AVAILABLE_DAY_SELECTOR = "td.dayA[data-handler='selectDay']"

# Path to chromedriver — on Raspberry Pi (apt install chromium-driver) this is the default
CHROMEDRIVER_PATH = "/usr/bin/chromedriver"


def _build_driver(headless: bool = True) -> webdriver.Chrome:
    opts = Options()
    opts.binary_location = "/usr/bin/chromium"
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")
    service = Service(executable_path=CHROMEDRIVER_PATH)
    return webdriver.Chrome(service=service, options=opts)


def _navigate_to_calendar(driver: webdriver.Chrome) -> WebDriverWait:
    """Opens the booking page and clicks through to the calendar (Terminauswahl)."""
    wait = WebDriverWait(driver, 20)

    driver.get(URL)

    # Step 1: service group
    wait.until(EC.element_to_be_clickable((By.ID, "sg82034txt"))).click()

    # Step 2: specific service "Wiederzulassung eines außer Betrieb gesetzten Fahrzeugs"
    wait.until(EC.element_to_be_clickable((By.ID, "217884"))).click()

    # Step 3: proceed button
    wait.until(EC.element_to_be_clickable((By.ID, "bp1"))).click()

    # Wait for the datepicker calendar to appear
    wait.until(EC.presence_of_element_located((By.CLASS_NAME, "ui-datepicker-calendar")))

    return wait


def _read_available_dates(driver: webdriver.Chrome) -> list[date]:
    """Reads all selectable days from the currently visible calendar month."""
    available = []
    cells = driver.find_elements(By.CSS_SELECTOR, AVAILABLE_DAY_SELECTOR)
    for cell in cells:
        try:
            month_0indexed = int(cell.get_attribute("data-month"))  # 0 = January
            year = int(cell.get_attribute("data-year"))
            day = int(cell.text.strip())
            available.append(date(year, month_0indexed + 1, day))
        except (ValueError, TypeError):
            continue
    return available


def _go_to_next_month(driver: webdriver.Chrome, wait: WebDriverWait) -> bool:
    """Clicks the datepicker 'next' arrow to advance one month.
    Returns False if the button is disabled (no more months available)."""
    try:
        next_btn = driver.find_element(By.CLASS_NAME, "ui-datepicker-next")
        if "ui-state-disabled" in next_btn.get_attribute("class"):
            return False
        next_btn.click()
        time.sleep(0.8)  # give datepicker time to re-render
        return True
    except Exception:
        return False


def check_availability(months_ahead: int = 2) -> dict:
    """
    Checks the calendar for available appointment slots.

    Args:
        months_ahead: how many additional months to check beyond the current one.

    Returns:
        {
            "available": bool,
            "available_dates": ["YYYY-MM-DD", ...],
        }
    """
    driver = _build_driver(headless=True)
    try:
        wait = _navigate_to_calendar(driver)

        all_dates: list[date] = []
        for _ in range(months_ahead + 1):
            all_dates.extend(_read_available_dates(driver))
            if not _go_to_next_month(driver, wait):
                break

        all_dates.sort()
        date_strings = [d.isoformat() for d in all_dates]

        return {
            "available": len(date_strings) > 0,
            "available_dates": date_strings,
        }
    finally:
        driver.quit()


def is_date_available(target: date, months_ahead: int = 2) -> bool:
    """Returns True if the given date has an open appointment slot."""
    result = check_availability(months_ahead=months_ahead)
    return target.isoformat() in result["available_dates"]


# ---------------------------------------------------------------------------
# Quick manual test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("Navigiere zum Kalender und lese verfügbare Termine...")
    result = check_availability(months_ahead=2)

    if result["available"]:
        print(f"Termine verfügbar ({len(result['available_dates'])} Tage):")
        for d in result["available_dates"]:
            print(f"  {d}")
    else:
        print("Keine Termine verfügbar.")
