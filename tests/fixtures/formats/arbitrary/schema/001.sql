CREATE TABLE records (id INTEGER PRIMARY KEY, label TEXT NOT NULL);
CREATE INDEX records_label ON records(label);
ALTER TABLE records ADD COLUMN extra TEXT;
