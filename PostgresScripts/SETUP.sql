CREATE TABLE members (
    chatId BIGINT UNIQUE NOT NULL,
    nickname TEXT NOT NULL,
    username TEXT,
    rank TEXT NOT NULL,
    createDatetime TIMESTAMP NOT NULL,
    lastUpdateDatetime TIMESTAMP NOT NULL,
    idParentMember BIGINT,
    CONSTRAINT fk_idParentMember FOREIGN KEY (idParentMember) REFERENCES members(chatId)
);

CREATE TABLE events (
    id INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    status TEXT NOT NULL,
    place TEXT NOT NULL,
    startDatetime TIMESTAMP NOT NULL,
    endDatetime TIMESTAMP NOT NULL,
    onlineDatetime TIMESTAMP NOT NULL,
    cutoffDatetime TIMESTAMP NOT NULL,
    players SMALLINT NOT NULL,
    price FLOAT NOT NULL,
    createDatetime TIMESTAMP NOT NULL,
    lastUpdateDatetime TIMESTAMP NOT NULL
);

CREATE TABLE lists (
    id INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    idEvents INTEGER NOT NULL,
    idMembers BIGINT NOT NULL,
    bkpNickname TEXT,
    emoji TEXT,
    status TEXT NOT NULL,
    orderDatetime TIMESTAMP NOT NULL,
    createDatetime TIMESTAMP NOT NULL,
    lastUpdateDatetime TIMESTAMP NOT NULL,
    CONSTRAINT fk_idEvent
        FOREIGN KEY (idEvents)
        REFERENCES events(id),
    CONSTRAINT fk_idMember
        FOREIGN KEY (idMembers)
        REFERENCES members(chatId),
    UNIQUE NULLS NOT DISTINCT (idEvents, idMembers, bkpNickname)
);
CREATE INDEX idx_lists_idMembers ON lists(idMembers);

CREATE TABLE commandLogs (
    id INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    chatId BIGINT NOT NULL,
    command TEXT NOT NULL,
    createDatetime TIMESTAMP NOT NULL,
    CONSTRAINT fk_chatId
        FOREIGN KEY (chatId)
        REFERENCES members(chatId)
);

CREATE INDEX idx_commandLogs_chatId ON commandLogs(chatId);

/* ----------------------------------- DML ---------------------------------- */
INSERT INTO members (chatId, nickname, rank, createDatetime, lastUpdateDatetime) VALUES (258936, 'Polo', 'Admin', now(), now());
INSERT INTO members (chatId, nickname, rank, createDatetime, lastUpdateDatetime) VALUES (1157261407, 'Lau', 'Admin', now(), now());

-- insert into events (place, startDatetime, endDatetime, onlineDatetime, cutoffDatetime, players, price, createdatetime, lastupdatedatetime, status)
-- values ('Crespi', '2025-09-21 11:30:00', '2025-09-21 13:00:00', '2025-09-16 19:00:00', '2025-09-19 19:00:00', 24, 202.5, now(), now(), 'NEW');