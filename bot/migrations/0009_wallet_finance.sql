CREATE TABLE IF NOT EXISTS user_wallets (
    telegram_user_id INTEGER PRIMARY KEY,
    balance INTEGER NOT NULL DEFAULT 0,
    currency TEXT NOT NULL DEFAULT 'تومان',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_pricing (
    telegram_user_id INTEGER PRIMARY KEY,
    price_per_gb INTEGER NOT NULL DEFAULT 0,
    price_per_day INTEGER NOT NULL DEFAULT 0,
    currency TEXT NOT NULL DEFAULT 'تومان',
    charge_basis TEXT NOT NULL DEFAULT 'allocated',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS wallet_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_user_id INTEGER NOT NULL,
    actor_user_id INTEGER,
    amount INTEGER NOT NULL,
    balance_after INTEGER NOT NULL,
    currency TEXT NOT NULL DEFAULT 'تومان',
    kind TEXT NOT NULL,
    operation TEXT,
    status TEXT NOT NULL DEFAULT 'completed',
    reference_transaction_id INTEGER,
    details TEXT,
    metadata_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(reference_transaction_id) REFERENCES wallet_transactions(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_wallet_transactions_telegram_user_id
    ON wallet_transactions(telegram_user_id);

CREATE INDEX IF NOT EXISTS idx_wallet_transactions_actor_user_id
    ON wallet_transactions(actor_user_id);

CREATE INDEX IF NOT EXISTS idx_wallet_transactions_reference_transaction_id
    ON wallet_transactions(reference_transaction_id);
