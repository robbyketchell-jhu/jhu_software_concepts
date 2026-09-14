## Robots.txt
An image was added at the root of this project: "robots.txt screenshot.png"
In the robots.txt file found at:https://www.thegradcafe.com/robots.txt, my IP address is not listed or prevented from scraping data so I am allowed to
proceed with webscraping.

Scrape.py
    1. Chrome: View > Developer > Allow JavaScript from Apple Events
    2. Open https://www.thegradcafe.com/survey in Chrome, clear the check
    3. Leave that Chrome window frontmost, then:

        python scrape.py              # pull until TARGET_RECORDS
        python scrape.py --resume     # continue after a stop
        python scrape.py --pages 5    # short test run

Progress is saved after every page. If it fails on anything page, you can rerun with --resume.

## Known Bugs
This is failing on about every few pages. I have to rerun with --resume. I was not able to debug this issue completely 
in time for the submission of this assignment.
