# Sort & Clean: relevance, unclassified items, archive

Open **Sort & Clean** in the menu.

## Relevance score (0-100)
Every item gets a score for how closely it is about tarbiyah:
- **Keyword rules** (always, free): pillar and topic keywords from the glossary and taxonomy, plus your
  **focus words**, found in the title (strongest), description and text.
- **AI** (when configured): after reading the item, the AI gives its own score and a one-line reason.
  It replaces the rules score.
- **You**: type a score on the item page (Edit this item → Relevance). Yours always wins.

Rough guide: 0 = unrelated, 20 = loosely related, 40+ = clearly about a pillar, 80+ = a central source.
The Library shows it as `rel. 49` (red below 20, amber 20-39, green 40+) and can sort and filter by it.

## Unclassified items (no pillar)
Library → Filters → Pillar → **Unclassified**. To sort them:
- **Sort & Clean → Step 1 → Sort unclassified items**. The keyword rules run again. With AI configured
  (and the box ticked), items the rules cannot place are sent to the AI, within the daily AI limit.
- Or by hand: select items in the Library → **Set pillar to…**, or open one item and tick its pillars.

## Archive vs delete
| | Archive | Delete |
|---|---|---|
| Hidden from library, search, research, reports | yes | yes |
| File and text kept | yes | no |
| Collected again later | no | no |
| Undo | Library → Show → Archive → **Bring back** | Library → Show → Deleted → **Restore** |

Clean-up in bulk: **Step 2** archives everything below a score (preview first).

## Keep new results relevant automatically
**Step 3**:
- **Focus words** raise the score of items that contain them (e.g. `حفظ القرآن`, `adolescence`).
- **Exclude words** archive new items whose title or description contains them (e.g. `football`).
- **Auto-archive below** archives new, automatically collected items under that score
  (15-20 is a good start). Your own uploads and manual additions are never archived automatically,
  and an item you brought back is never archived again automatically.

After changing words, click **Re-score the whole library**.

**Step 4** lists each source with the share of relevant items it brings; disable or narrow noisy ones.
The daily report shows how many new items were archived as not relevant.
