-- SQL test file
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(255) UNIQUE,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE VIEW active_users AS
SELECT id, name, email
FROM users
WHERE active = true;

CREATE INDEX idx_users_email ON users(email);

CREATE FUNCTION add_nums(a INT, b INT)
RETURNS INT AS $$
BEGIN
    RETURN a + b;
END;
$$ LANGUAGE plpgsql;
