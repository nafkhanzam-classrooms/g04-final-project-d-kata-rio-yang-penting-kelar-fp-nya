CREATE DATABASE IF NOT EXISTS g04_db
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE g04_db;

-- SCHEMA START BELOW!!!

-- Created by Redgate Data Modeler (https://datamodeler.redgate-platform.com)
-- Last modification date: 2026-06-12 02:48:24.063

-- tables
-- Table: permissions
CREATE TABLE permissions (
    id int  NOT NULL AUTO_INCREMENT,
    code varchar(32)  NOT NULL UNIQUE,
    description longtext  NOT NULL,
    CONSTRAINT permissions_pk PRIMARY KEY (id)
);

-- Table: role
CREATE TABLE role (
    id int  NOT NULL AUTO_INCREMENT,
    name varchar(32)  NOT NULL UNIQUE,
    description longtext  NOT NULL,
    CONSTRAINT role_pk PRIMARY KEY (id)
);

-- Table: role_permissions
CREATE TABLE role_permissions (
    role_id int  NOT NULL,
    permissions_id int  NOT NULL,
    CONSTRAINT role_permissions_pk PRIMARY KEY (role_id,permissions_id)
);

-- Table: users
CREATE TABLE users (
    id int  NOT NULL AUTO_INCREMENT,
    username varchar(32)  NOT NULL UNIQUE,
    name varchar(64)  NOT NULL,
    email varchar(64)  NOT NULL UNIQUE,
    password_hash varchar(255)  NOT NULL,
    is_active boolean  NOT NULL DEFAULT TRUE,
    created_at timestamp  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp  NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    role_id int  NOT NULL,
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
