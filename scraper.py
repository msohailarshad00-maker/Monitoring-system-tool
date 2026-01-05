import pandas as pd
import time
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from seleniumbase import SB
from selenium.webdriver.common.by import By

# ---------------- CONFIG ----------------
SEEN_FILE = "seen_reviews.csv"
DB_FILE = "all_bad_reviews_db.csv"
NEW_FILE = "new_bad_reviews.xlsx"

EMAIL_FROM = "markcraft494@gmail.com"
EMAIL_TO = os.environ.get("EMAIL_TO", "msohailarshad00@gmail.com")
EMAIL_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]

MAX_SCROLLS = 4

SPREADSHEET_ID = "1dX6iCgY6B8drj1ZwW6VorDT6G3tUU2h2PBz5Xst5jPQ"
WORKSHEET_NAME = "Sheet1"

# ---------------- EMAIL FUNCTION ----------------
def send_email_with_attachment(file_path, new_count):
    if new_count == 0:
        return
    msg = MIMEMultipart()
    msg["From"] = EMAIL_FROM
    msg["To"] = EMAIL_TO
    msg["Subject"] = f"🚨 {new_count} New Bad Google Reviews"

    body = f"Hi Mark,\n\nFound {new_count} new bad reviews. See attached file.\n\nRegards,\nBot"
    msg.attach(MIMEText(body, "plain"))

    with open(file_path, "rb") as f:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(f.read())
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", f"attachment; filename={os.path.basename(file_path)}")
    msg.attach(part)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_FROM, EMAIL_PASSWORD)
        server.send_message(msg)
    print(f"📧 Email sent with {new_count} new bad reviews!")

# ---------------- GOOGLE SHEET SETUP ----------------
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import json

creds_json = os.environ["GOOGLE_CREDENTIALS_JSON"]
credentials = ServiceAccountCredentials.from_json_keyfile_dict(json.loads(creds_json), [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets"
])
gc = gspread.authorize(credentials)

try:
    sh = gc.open_by_key(SPREADSHEET_ID)
    worksheet = sh.worksheet(WORKSHEET_NAME)
    data = worksheet.get_all_records()
    profiles = pd.DataFrame(data)
    print(f"✅ Loaded {len(profiles)} profiles from Google Sheet")
except Exception as e:
    print(f"❌ Google Sheet error: {e}")
    raise

# Load persistence files
seen_ids = set(pd.read_csv(SEEN_FILE)["review_id"]) if os.path.exists(SEEN_FILE) else set()
db_exists = os.path.exists(DB_FILE)
new_reviews_list = []

# ---------------- MAIN LOOP ----------------
with SB(uc=True, xvfb=True) as sb:  # ← Key: SB + xvfb for undetected on Linux CI
    driver = sb.driver  # Access raw driver if needed

    for _, row in profiles.iterrows():
        business = row["Name"]
        url = row["Profil"].replace("Google - ", "").strip()
        print(f"\n🔍 Checking: {business} - {url}")

        try:
            sb.open(url)
            sb.sleep(12)  # Wait for redirect

            # Click Reviews tab
            sb.click('button[role="tab"]:has-text("Reviews")', timeout=30)
            sb.sleep(5)

            # Sort by newest
            try:
                sb.click('button[aria-label="Sort reviews"]')
                sb.sleep(2)
                sb.click('#fDahXd div:nth-child(2)')
                sb.sleep(3)
            except:
                print("Sort failed - continuing")

            # Scroll
            scrollable = driver.find_element(By.XPATH, "//div[@role='main']")
            for _ in range(MAX_SCROLLS):
                sb.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight", scrollable)
                sb.sleep(4)

            # Scrape reviews
            reviews = driver.find_elements(By.CSS_SELECTOR, "div.jftiEf")
            for review in reviews:
                try:
                    review_id = review.get_attribute("data-review-id")
                    if not review_id or review_id in seen_ids:
                        continue

                    rating_str = review.find_element(By.CSS_SELECTOR, "span.kvMYJc").get_attribute("aria-label")
                    rating = int(rating_str.split()[0]) if rating_str else 5
                    if rating > 3:
                        continue

                    record = row.to_dict()
                    record.update({
                        "Reviewer Name": review.find_element(By.CSS_SELECTOR, "div.d4r55").text,
                        "Rating": rating,
                        "Review Date": review.find_element(By.CSS_SELECTOR, "span.rsqaWe").text,
                        "Review Text": review.find_element(By.CSS_SELECTOR, "span.wiI7pd").text,
                        "Profile Image URL": review.find_element(By.CSS_SELECTOR, "img.NBa7we").get_attribute("src"),
                        "Review ID": review_id,
                        "Source URL": url,
                        "Scraped At": time.strftime("%Y-%m-%d %H:%M:%S")
                    })

                    new_reviews_list.append(record)
                    pd.DataFrame([record]).to_csv(DB_FILE, mode="a", header=not db_exists, index=False)
                    db_exists = True
                    seen_ids.add(review_id)

                except Exception as e:
                    print(f"Review scrape error: {e}")
                    continue

        except Exception as e:
            print(f"⚠️ Error on {business}: {e}")
            continue

# ---------------- SAVE & EMAIL ----------------
pd.DataFrame({"review_id": list(seen_ids)}).to_csv(SEEN_FILE, index=False)

if new_reviews_list:
    df_new = pd.DataFrame(new_reviews_list)
    df_new.to_excel(NEW_FILE, index=False)
    send_email_with_attachment(NEW_FILE, len(new_reviews_list))
else:
    print("\n✅ No new bad reviews found.")
