-- When login as postgres user

-- Create user
CREATE USER volley_user WITH ENCRYPTED PASSWORD '<pass>';

-- Grant privileges on all tables in volley.public to volley_user
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA volley.public TO volley_user;

-- Automatically grant privileges for new tables in the future
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL PRIVILEGES ON TABLES TO volley_user;

-- To revoke this privileges and drop user, in order
-- REVOKE ALL ON all TABLES IN SCHEMA public FROM volley_user;
-- ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL PRIVILEGES ON TABLES FROM volley_user;
-- REVOKE ALL ON SCHEMA public FROM volley_user;
-- drop user volley_user;