ALTER TABLE repair_cases ADD COLUMN mode TEXT NOT NULL DEFAULT 'edit-first' CHECK(mode IN ('edit-first','review-first'));
ALTER TABLE repair_cases ADD COLUMN allow_slide_changes INTEGER NOT NULL DEFAULT 0 CHECK(allow_slide_changes IN (0,1));
