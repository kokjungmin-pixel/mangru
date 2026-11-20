"""ADV Part 2A 브로셔 나누기 테스트 (B3, B7 여섯·일곱째 줄).
가짜 브로셔는 실제 데모 3곳 현재 브로셔의 모양을 본떴다 (docs/verified.md 2026-11-21)."""
from src.collect.form_adv import item2_declares_no_change, split_items

COVER = "Example Capital Management, LLC\nForm ADV Part 2A\nMarch 31, 2026"
TOC = ("Item 3. Table of Contents\n"
       "Item 2. Material Changes ........................................ 2\n"
       "Item 4. Advisory Business………………………………………………3\n"
       "Item 8. Methods of Analysis, Investment Strategies and Risk of Loss ........ 3\n"
       "Item 9. Disciplinary Information ............................. 3")
BODY_4 = "Item 4. Advisory Business\nWe manage concentrated long-only equity portfolios."
BODY_8 = ("Item 8. Methods of Analysis, Investment Strategies and Risk of Loss\n"
          "We buy and hold a small number of high-quality businesses for the long term.")
BODY_9 = "Item 9. Disciplinary Information\nThere are no legal or disciplinary events."


def test_skips_table_of_contents_and_finds_start_pages():
    pages = [COVER + "\n" + TOC,
             "Item 2. Material Changes\nThere have been no material changes since the last update.",
             BODY_4 + "\n" + BODY_8 + "\n" + BODY_9]
    items, starts = split_items(pages)
    assert items["2"].startswith("There have been no material changes")
    assert items["8"].startswith("We buy and hold") and "Disciplinary" not in items["8"]
    assert starts == {"2": 2, "3": 1, "4": 3, "8": 3, "9": 3}


def test_item_references_inside_item2_are_not_headings():
    # Brown: "Item 4.E was amended ..." / Warburg: 줄바꿈된 "Item 8. Methods ..., Item 10. Other ..."
    item2 = ("Item 2 – Material Changes\n"
             "The following changes have been made since our last annual amendment:\n"
             "Item 4.E was amended to update the Assets Under Management as of\n"
             "Item 13.A was amended to update Periodic Review of Accounts\n"
             "including with respect to Item 4. Advisory Business, Item 7, Types of Clients,\n"
             "Item 8. Methods of Analysis, Investment Strategies and Risk of Loss, Item 10. Other Financial Industry\n"
             "Activities and Affiliations.")
    items, starts = split_items([COVER, item2, BODY_4 + "\n" + BODY_8 + "\n" + BODY_9])
    assert "Item 13.A was amended" in items["2"] and items["2"].endswith("Activities and Affiliations.")
    assert "13" not in items
    assert starts["8"] == 3 and items["8"].startswith("We buy and hold")


def test_stops_before_part_2b_supplement():
    # Akre: 본문 뒤 "Brochure Supplement" 부터는 Part 2B. 그 안의 Item 2 가 더 길어도 잡지 않는다
    supplement = ("Brochure Supplement\nJohn Neff\nThis brochure supplement provides information about John Neff.\n"
                  "Item 2. Educational Background and Business Experience\n" + "He joined the firm in 2009. " * 30)
    pages = [COVER, "Item 2. Material Changes\nRoutine updates only.",
             BODY_4 + "\n" + BODY_8 + "\n" + BODY_9, supplement]
    items, starts = split_items(pages)
    assert items["2"] == "Routine updates only." and starts["2"] == 2
    assert "John Neff" not in items["9"]


def test_item2_declares_no_change():
    assert item2_declares_no_change("There have been no material changes since our last annual update.") is True
    assert item2_declares_no_change("The following changes have been made:\nItem 4.E was amended.") is False
    assert item2_declares_no_change("") is None and item2_declares_no_change(None) is None


def test_toc_lines_are_dropped_from_bodies():
    # Akre: "Item 3" 제목 없이 Item 2 바로 뒤에 목차가 와서 Item 2 본문에 목차 줄이 붙음
    pages = [COVER, "Item 2. Material Changes\nThere have been no material changes.\n2",
             "Table of Contents\n" + "\n".join(TOC.splitlines()[1:]), BODY_4 + "\n" + BODY_8 + "\n" + BODY_9]
    items, _ = split_items(pages)
    assert "...." not in items["2"] and "………" not in items["2"]
    assert len(items["2"]) < 80
    assert item2_declares_no_change(items["2"]) is True
