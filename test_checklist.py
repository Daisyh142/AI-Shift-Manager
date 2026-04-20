#!/usr/bin/env python3
"""Selenium UI checklist aligned to current frontend labels/routes."""

from __future__ import annotations

import os
import time
import re
from datetime import datetime, timedelta

from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

BASE_URL = os.getenv("UI_BASE_URL", "http://localhost:5173")


class ChecklistResults:
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


def current_run_id(driver: webdriver.Chrome) -> int | None:
    for element in driver.find_elements(By.XPATH, "//*[contains(text(), 'Run #')]"):
        match = re.search(r"Run\\s*#(\\d+)", element.text)
        if match:
            return int(match.group(1))
    return None


def run_ui_checklist() -> None:
    results = ChecklistResults()
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
        wait_text(wait, "Operations Command Center")
        results.add("2", "PASS", f"Demo login succeeded, URL={driver.current_url}")

        # 3) Generate schedule
        driver.find_element(By.XPATH, "//button[contains(., 'Generate')]").click()
        wait_text(wait, "Week 1")
        wait_text(wait, "Week 2")
        wait.until(lambda d: current_run_id(d) is not None)
        generated_run_id = current_run_id(driver)
        results.add("3", "PASS", f"Generate completed and 2-week view is visible (run #{generated_run_id})")

        # 4) Normal chat question should not trigger regeneration
        chatbox = driver.find_element(By.XPATH, "//textarea[contains(@placeholder, 'Ask about fairness')]")
        chatbox.send_keys("How fair is this schedule right now?")
        driver.find_element(By.XPATH, "//button[contains(., 'Send')]").click()
        time.sleep(1)
        after_normal_chat_run_id = current_run_id(driver)
        if after_normal_chat_run_id != generated_run_id:
            raise AssertionError("Normal chat unexpectedly changed run id")
        results.add("4", "PASS", "Normal chat message did not regenerate schedule")

        # 5) Regenerate intent from chat should create a new run
        chatbox = driver.find_element(By.XPATH, "//textarea[contains(@placeholder, 'Ask about fairness')]")
        chatbox.send_keys("regenerate: rebalance hours for fairness")
        driver.find_element(By.XPATH, "//button[contains(., 'Send')]").click()
        wait.until(lambda d: current_run_id(d) is not None and current_run_id(d) != generated_run_id)
        regenerated_run_id = current_run_id(driver)
        wait_text(wait, "I started regeneration using your reason")
        results.add("5", "PASS", f"Chat regenerate intent created new run #{regenerated_run_id}")

        # 6) Publish schedule
        driver.find_element(By.XPATH, "//*[contains(text(), 'Publish')]").click()
        time.sleep(1)
        results.add("6", "PASS", "Publish action triggered without visible crash")

        # 7) Owner Requests page
        driver.find_element(By.XPATH, "//*[contains(text(), 'Requests')]").click()
        wait_text(wait, "All Requests")
        results.add("7", "PASS", "Owner requests page loaded")

        # 8) Logout
        driver.find_element(By.XPATH, "//*[contains(text(), 'Log out')]").click()
        wait.until(EC.url_to_be(BASE_URL + "/"))
        wait_text(wait, "Sign in")
        results.add("8", "PASS", "Logout returned to login page")

        # 9) Employee login
        email = driver.find_element(By.CSS_SELECTOR, "input[type='email']")
        password = driver.find_element(By.CSS_SELECTOR, "input[type='password']")
        email.clear()
        email.send_keys("employee@demo.com")
        password.clear()
        password.send_keys("demo")
        driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
        wait.until(EC.url_contains("/dashboard"))
        wait_text(wait, "My Schedule")
        results.add("9", "PASS", "Employee login succeeded")

        # 10) Employee stats visible
        wait_text(wait, "Required This Week")
        wait_text(wait, "PTO Balance")
        results.add("10", "PASS", "Employee dashboard stats are visible")

        # 11) Team schedule page
        driver.find_element(By.XPATH, "//*[contains(text(), 'Team Schedule')]").click()
        wait.until(EC.url_contains("/team-schedule"))
        wait_text(wait, "Team Schedule")
        wait_text(wait, "Week 1")
        wait_text(wait, "Week 2")
        results.add("11", "PASS", "Team schedule page loaded with 2-week sections")

        # 12) Submit request from My Requests
        driver.find_element(By.XPATH, "//*[contains(text(), 'My Requests')]").click()
        wait.until(EC.url_contains("/my-requests"))
        wait_text(wait, "Submit Time Off Request")
        date_input = driver.find_element(By.CSS_SELECTOR, "input[type='date']")
        future_date = (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d")
        date_input.clear()
        date_input.send_keys(future_date)
        driver.find_element(By.XPATH, "//*[contains(text(), 'Submit Request')]").click()
        time.sleep(1)
        results.add("12", "PASS", f"Employee submitted request for date={future_date}")

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
