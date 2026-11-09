-- Separate database for integration tests (TEST_DATABASE_URL), so test runs that downgrade
-- migrations never touch the development database.
CREATE DATABASE travelbuddy_test OWNER travelbuddy;
\connect travelbuddy_test
CREATE EXTENSION IF NOT EXISTS postgis;
