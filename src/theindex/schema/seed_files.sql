-- SPDX-License-Identifier: MIT
-- seed_files.sql -- built-in rows for locations, files, titles, fleet and OS sources. Re-applied: idempotent.

INSERT OR IGNORE INTO ref_collector (code, display, description, sort_order) VALUES
 ('filetree','File tree','Directories, files and document titles',8),
 ('catalog','Catalog','Imported offline file lists',9),
 ('inbox','Inbox','Payloads taken from the shared inbox folder',10),
 ('pull','Pull','Payloads fetched from members over ssh',11);

INSERT OR IGNORE INTO ref_reach (code, display, description, sort_order) VALUES
 ('offline','Offline','Imported file list of a drive or backup that is not connected',5),
 ('inbox','Inbox','Sends payloads through the shared inbox folder',6);

INSERT OR IGNORE INTO ref_gap_kind (code, display, description, sort_order) VALUES
 ('network','Network mount','Network mount not walked: its own machine indexes it',5),
 ('budget','Time budget','Walk stopped at its time limit; last values kept',6),
 ('unreadable','Unreadable','Files or folders that could not be read',7),
 ('unsupported','Unsupported','Not available on this operating system',8),
 ('index_mismatch','Index mismatch','The OS index and the walk disagree',9),
 ('bad_payload','Bad payload','An inbox file could not be read',10);

INSERT OR IGNORE INTO ref_agent_marker (code, display, description, sort_order) VALUES
 ('AGENTS.md','AGENTS.md','Cross-vendor agent instructions',1),
 ('CLAUDE.md','CLAUDE.md','Claude Code instructions',2),
 ('.claude','.claude','Claude Code project folder',3),
 ('GEMINI.md','GEMINI.md','Gemini CLI instructions',4),
 ('.cursorrules','.cursorrules','Cursor rules (legacy file)',5),
 ('.cursor','.cursor','Cursor project folder',6),
 ('.github/copilot-instructions.md','Copilot','GitHub Copilot instructions',7),
 ('.windsurfrules','.windsurfrules','Windsurf rules',8),
 ('.aider.conf.yml','Aider','Aider configuration',9),
 ('.clinerules','.clinerules','Cline rules',10);

INSERT OR IGNORE INTO ref_title_type (code, display, description, definition, sort_order) VALUES
 ('.md','Markdown','Front matter title, else first heading','md',1),
 ('.markdown','Markdown','Front matter title, else first heading','md',2),
 ('.html','HTML','<title>','html',3), ('.htm','HTML','<title>','html',4),
 ('.docx','Word','Office core properties','ooxml',5), ('.xlsx','Excel','Office core properties','ooxml',6),
 ('.pptx','PowerPoint','Office core properties','ooxml',7),
 ('.odt','ODF text','ODF meta.xml','odf',8), ('.ods','ODF sheet','ODF meta.xml','odf',9),
 ('.odp','ODF slides','ODF meta.xml','odf',10),
 ('.epub','EPUB','Package dc:title','epub',11), ('.pdf','PDF','XMP dc:title, else Info /Title','pdf',12);

INSERT OR IGNORE INTO setting (key, value) VALUES
 ('filetree_full_every', '7'), ('filetree_title_budget', '20000'), ('filetree_titles', '1');
