# StatLine setup (about 15 minutes, easiest on a computer)

This folder has everything for a fresh start:

- index.html: the website
- build_data.py: builds data/nfl.json from free nflverse data
- build_nba.py: builds data/nba.json (NBA matchups, injuries, player logs)
- build_nhl.py: builds data/nhl.json (NHL matchups, injuries, player logs)
- update-data.yml: the schedule file (it goes in a special folder, see step 3)

## Steps

1. Go to github.com, click the "+" at the top right, then "New repository."
   Name it statline, choose Public, check "Add a README file," and click "Create repository."

2. Click "Add file," then "Upload files." Drag in index.html and build_data.py
   (not update-data.yml). Click "Commit changes."

3. Click "Add file," then "Create new file." In the name box type exactly:
   .github/workflows/update-data.yml
   (typing each slash makes a folder). Open update-data.yml from this folder in a
   text editor, copy ALL of it, paste it into the big box, and click "Commit changes."

4. Click the Settings tab, then Actions, then General. Under "Workflow permissions"
   choose "Read and write permissions" and click Save.

5. Click the Actions tab, then "Update NFL data," then "Run workflow." Wait for a
   green check (a few minutes). Then open the data folder in the Code tab. You should
   see nfl.json and log.txt. If the run fails, open data/log.txt and send me what it says.

6. Click Settings, then Pages. Under "Branch," choose main and "/ (root)," then Save.

7. After a minute or two, the Pages screen shows your site address:
   https://YOURUSERNAME.github.io/statline/
   If it looks old, add ?v=2 to the end of the address.

## Notes

- The schedule refreshes the data every day, with extra runs on game days.
- A warning about Node.js on the Actions page is harmless.
- To change a file later, upload a file with the same name. It replaces the old one.
- build_nba.py and build_nhl.py go in the same place as build_data.py.
- Each sport has a Player checker: type a player, pick a stat, enter a number.
- MLB shows "coming soon" for now. It needs its own data feed.
- The NFL and NBA data files are written to data/log.txt, data/nba_log.txt, and data/nhl_log.txt. If a run fails, open those.
