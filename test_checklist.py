#!/usr/bin/env python3
"""Selenium UI checklist aligned to current frontend labels/routes."""

from __future__ import annotations

import time
from datetime import datetime, timedelta

from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

BASE_URL = "http://127.0.0.1:5173"


class TestResults:
    def __init__(self) -> None:
        self.results: list[dict[str, str]] = []

    def add(self, step: str, status: str, observation: str, error: str = "None") -> None:
        self.results.append({"step": step, "status": status, "observation": observation, "error": error})

    def print(self) -> None:
        print("\n" + "=" * 80)
        print("UI TEST RESULTS")
        print("=" * 80)
        for item in self.results:
            print(f"\nStep {item['step']}: {item['status']}")
            print(f"  Observation: {item['observation']}")
            if item["error"] != "None":
                print(f"  Error: {item['error']}")
        passed = sum(1 for item in self.results if item["status"] == "PASS")
        failed = sum(1 for item in self.results if item["status"] == "FAIL")
        print("\n" + "=" * 80)
        print(f"Summary: {passed} PASSED, {failed} FAILED out of {len(self.results)} tests")
        print("=" * 80 + "\n")


def setup_driver() -> webdriver.Chrome:
    options = webdriver.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1440,900")
    driver = webdriver.Chrome(options=options)
    driver.implicitly_wait(4)
    return driver


def wait_text(wait: WebDriverWait, text: str) -> None:
    wait.until(EC.presence_of_element_located((By.XPATH, f"//*[contains(text(), '{text}')]")))


def run_ui_checklist() -> None:
    results = TestResults()
    driver = setup_driver()
    wait = WebDriverWait(driver, 12)

    try:
        # 1) Home page and login form
        driver.get(BASE_URL)
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='email']")))
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='password']")))
        wait_text(wait, "Try Demo Data")
        results.add("1", "PASS", "Home page loaded with login form and demo button")

        # 2) Try demo login
        demo_btn = driver.find_element(By.XPATH, "//*[contains(text(), 'Try Demo Data')]")
        demo_btn.click()
        wait.until(EC.url_contains("/dashboard"))
        wait_text(wait, "Schedule Actions")
        results.add("2", "PASS", f"Demo login succeeded, URL={driver.current_url}")

        # 3) Generate schedule
        driver.find_element(By.XPATH, "//*[contains(text(), 'Generate Schedule')]").click()
        wait_text(wait, "Current schedule run ID")
        results.add("3", "PASS", "Generate schedule action completed and run ID shown")

        # 4) Publish schedule
        driver.find_element(By.XPATH, "//*[contains(text(), 'Publish')]").click()
        time.sleep(1)
        results.add("4", "PASS", "Publish action triggered without visible crash")

        # 5) Owner Requests page
        driver.find_element(By.XPATH, "//*[contains(text(), 'Requests')]").click()
        wait_text(wait, "All Requests")
        results.add("5", "PASS", "Owner requests page loaded")

        # 6) Logout
        driver.find_element(By.XPATH, "//*[contains(text(), 'Log out')]").click()
        wait.until(EC.url_to_be(BASE_URL + "/"))
        wait_text(wait, "Sign in")
        results.add("6", "PASS", "Logout returned to login page")

        # 7) Employee login
        email = driver.find_element(By.CSS_SELECTOR, "input[type='email']")
        password = driver.find_element(By.CSS_SELECTOR, "input[type='password']")
        email.clear()
        email.send_keys("employee@demo.com")
        password.clear()
        password.send_keys("demo")
        driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
        wait.until(EC.url_contains("/dashboard"))
        wait_text(wait, "My Schedule")
        results.add("7", "PASS", "Employee login succeeded")

        # 8) Employee stats visible
        wait_text(wait, "Weekly Required Hours")
        wait_text(wait, "PTO Balance")
        results.add("8", "PASS", "Employee dashboard stats are visible")

        # 9) Team schedule page
        driver.find_element(By.XPATH, "//*[contains(text(), 'Team Schedule')]").click()
        wait.until(EC.url_contains("/team-schedule"))
        wait_text(wait, "Team Schedule")
        results.add("9", "PASS", "Team schedule page loaded")

        # 10) Submit request from My Requests
        driver.find_element(By.XPATH, "//*[contains(text(), 'My Requests')]").click()
        wait.until(EC.url_contains("/my-requests"))
        wait_text(wait, "Submit Time Off Request")
        date_input = driver.find_element(By.CSS_SELECTOR, "input[type='date']")
        future_date = (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d")
        date_input.clear()
        date_input.send_keys(future_date)
        driver.find_element(By.XPATH, "//*[contains(text(), 'Submit Request')]").click()
        time.sleep(1)
        results.add("10", "PASS", f"Employee submitted request for date={future_date}")

    except TimeoutException as exc:
        results.add("fatal", "FAIL", "UI timeout while waiting for expected element", str(exc))
    except Exception as exc:  # noqa: BLE001
        results.add("fatal", "FAIL", "Unexpected UI test failure", str(exc))
    finally:
        driver.quit()
        results.print()


if __name__ == "__main__":
    print("Starting UI checklist test...")
    print(f"Target URL: {BASE_URL}")
    run_ui_checklist()
