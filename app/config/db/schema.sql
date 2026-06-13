CREATE DATABASE IF NOT EXISTS g04_db
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE g04_db;

DROP TABLE IF EXISTS quiz_answers;
DROP TABLE IF EXISTS quiz_questions;
DROP TABLE IF EXISTS quizzes;
DROP TABLE IF EXISTS class_news;
DROP TABLE IF EXISTS classroom_participants;
DROP TABLE IF EXISTS classrooms;
DROP TABLE IF EXISTS users;

DROP TABLE IF EXISTS role_permissions;
DROP TABLE IF EXISTS users;
DROP TABLE IF EXISTS permissions;
DROP TABLE IF EXISTS role;

-- SCHEMA START BELOW!!!

-- Created by Redgate Data Modeler (https://datamodeler.redgate-platform.com)
-- Last modification date: 2026-06-12 02:48:24.063

-- tables
-- Table: permissions
CREATE TABLE IF NOT EXISTS permissions (
    id INT  NOT NULL AUTO_INCREMENT,
    code VARCHAR(32)  NOT NULL UNIQUE,
    description LONGTEXT  NOT NULL,
    CONSTRAINT permissions_pk PRIMARY KEY (id)
);

-- Table: role
CREATE TABLE IF NOT EXISTS role (
    id INT  NOT NULL AUTO_INCREMENT,
    name VARCHAR(32)  NOT NULL UNIQUE,
    description LONGTEXT  NOT NULL,
    CONSTRAINT role_pk PRIMARY KEY (id)
);

-- Table: role_permissions
CREATE TABLE IF NOT EXISTS role_permissions (
    role_id INT  NOT NULL,
    permissions_id INT  NOT NULL,
    CONSTRAINT role_permissions_pk PRIMARY KEY (role_id,permissions_id)
);

-- Table: users
CREATE TABLE IF NOT EXISTS users (
    id INT  NOT NULL AUTO_INCREMENT,
    username VARCHAR(32)  NOT NULL UNIQUE,
    name VARCHAR(64)  NOT NULL,
    email VARCHAR(64)  NOT NULL UNIQUE,
    password_hash VARCHAR(255)  NOT NULL,
	display_name VARCHAR(100),
	total_poINTs INT DEFAULT 0,
	streak_days INT DEFAULT 0,
	last_active DATE,
    is_active BOOLEAN  NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP  NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    role_id INT  NOT NULL,
    CONSTRAINT users_pk PRIMARY KEY (id)
);

-- foreign keys
-- Reference: role_permissions_permissions (table: role_permissions)
ALTER TABLE role_permissions ADD CONSTRAINT role_permissions_permissions FOREIGN KEY role_permissions_permissions (permissions_id)
    REFERENCES permissions (id);

-- Reference: role_permissions_role (table: role_permissions)
ALTER TABLE role_permissions ADD CONSTRAINT role_permissions_role FOREIGN KEY role_permissions_role (role_id)
    REFERENCES role (id);

-- Reference: users_roles (table: users)
ALTER TABLE users ADD CONSTRAINT users_roles FOREIGN KEY users_roles (role_id)
    REFERENCES role (id);

-- End of file.

-- alfred's work on feat/dashboard

CREATE TABLE IF NOT EXISTS classrooms (
	id INT PRIMARY KEY AUTO_INCREMENT,
	name VARCHAR(200) NOT NULL,
	description LONGTEXT,
	code VARCHAR(8) UNIQUE NOT NULL,
	host_id INT NOT NULL,
	mode VARCHAR(20) DEFAULT 'quiz_only',
	is_active INT DEFAULT 1,
	created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
	FOREIGN KEY (host_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS classroom_participants (
	id INT PRIMARY KEY AUTO_INCREMENT,
	classroom_id INT NOT NULL,
	user_id INT NOT NULL,
	role VARCHAR(20) DEFAULT 'participant',
	joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
	FOREIGN KEY (classroom_id) REFERENCES classrooms(id),
	FOREIGN KEY (user_id) REFERENCES users(id), UNIQUE(classroom_id, user_id)
);

CREATE TABLE IF NOT EXISTS quizzes (
	id INT PRIMARY KEY AUTO_INCREMENT,
	classroom_id INT NOT NULL,
	title VARCHAR(200) NOT NULL,
	is_active INT DEFAULT 0,
	created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
	FOREIGN KEY (classroom_id) REFERENCES classrooms(id)
);

CREATE TABLE IF NOT EXISTS quiz_questions (
	id INT PRIMARY KEY AUTO_INCREMENT,
	quiz_id INT NOT NULL,
	question LONGTEXT NOT NULL,
	option_a VARCHAR(500) NOT NULL,
	option_b VARCHAR(500) NOT NULL,
	option_c VARCHAR(500) NOT NULL,
	option_d VARCHAR(500) NOT NULL,
	correct_option CHAR(1) NOT NULL,
	time_limit INT DEFAULT 30,
	poINTs INT DEFAULT 100,
	question_order INT DEFAULT 0,
	FOREIGN KEY (quiz_id) REFERENCES quizzes(id)
);

CREATE TABLE IF NOT EXISTS quiz_answers (
	id INT PRIMARY KEY AUTO_INCREMENT,
	question_id INT NOT NULL,
	user_id INT NOT NULL,
	selected_option CHAR(1) NOT NULL,
	is_correct INT DEFAULT 0,
	poINTs_earned INT DEFAULT 0,
	answered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
	FOREIGN KEY (question_id) REFERENCES quiz_questions(id),
	FOREIGN KEY (user_id) REFERENCES users(id),
	UNIQUE(question_id, user_id)
);

CREATE TABLE IF NOT EXISTS class_news (
	id INT PRIMARY KEY AUTO_INCREMENT,
	classroom_id INT NOT NULL,
	author_id INT NOT NULL,
	title VARCHAR(200) NOT NULL,
	content LONGTEXT,
	created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
	FOREIGN KEY (classroom_id) REFERENCES classrooms(id),
	FOREIGN KEY (author_id) REFERENCES users(id)
);

-- Seed data

INSERT IGNORE INTO role (name, description) VALUES
    ('admin',     'Full system access'),
    ('presenter', 'Can upload and control presentations'),
    ('viewer',    'Can view presentations only');

INSERT IGNORE INTO permissions (code, description) VALUES
    ('ppt.upload',  'Upload PPT/PPTX files'),
    ('ppt.control', 'Control slide navigation'),
    ('ppt.view',    'View presentation slides'),
    ('user.manage', 'Manage user accounts and roles');

-- admin gets everything
INSERT IGNORE INTO role_permissions (role_id, permissions_id)
SELECT r.id, p.id FROM role r, permissions p WHERE r.name = 'admin';

-- presenter gets upload, control, view
INSERT IGNORE INTO role_permissions (role_id, permissions_id)
SELECT r.id, p.id FROM role r, permissions p
WHERE r.name = 'presenter' AND p.code IN ('ppt.upload', 'ppt.control', 'ppt.view');

-- viewer gets view only
INSERT IGNORE INTO role_permissions (role_id, permissions_id)
SELECT r.id, p.id FROM role r, permissions p
WHERE r.name = 'viewer' AND p.code = 'ppt.view';
