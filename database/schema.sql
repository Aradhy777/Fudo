-- =====================================================================
-- ExpenseTrack: Smart Student Expense Manager
-- Database Schema for MySQL 8.0+
-- Database: expensetrack
-- Character Set: utf8mb4, Collation: utf8mb4_unicode_ci
-- =====================================================================

CREATE DATABASE IF NOT EXISTS `expensetrack`
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE `expensetrack`;

-- Disable foreign key checks during schema creation
SET FOREIGN_KEY_CHECKS = 0;

-- 1. Users Table
DROP TABLE IF EXISTS `users`;
CREATE TABLE `users` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `username` VARCHAR(50) NOT NULL UNIQUE,
  `email` VARCHAR(100) NOT NULL UNIQUE,
  `password_hash` VARCHAR(255) NOT NULL,
  `full_name` VARCHAR(100) NOT NULL,
  `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX `idx_users_email` (`email`),
  INDEX `idx_users_username` (`username`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 2. Categories Table
DROP TABLE IF EXISTS `categories`;
CREATE TABLE `categories` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `name` VARCHAR(50) NOT NULL UNIQUE,
  `icon` VARCHAR(50) NOT NULL DEFAULT 'tag',
  `color` VARCHAR(20) NOT NULL DEFAULT '#10B981',
  `is_system` BOOLEAN NOT NULL DEFAULT TRUE,
  `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX `idx_categories_name` (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 3. Uploaded Receipts Table
DROP TABLE IF EXISTS `uploaded_receipts`;
CREATE TABLE `uploaded_receipts` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `user_id` INT NOT NULL,
  `file_name` VARCHAR(255) NOT NULL,
  `file_path` VARCHAR(500) NOT NULL,
  `file_size` INT NOT NULL,
  `mime_type` VARCHAR(100) NOT NULL,
  `azure_blob_url` VARCHAR(500) NULL,
  `ocr_raw_text` MEDIUMTEXT NULL,
  `ocr_status` ENUM('pending', 'success', 'failed', 'fallback') NOT NULL DEFAULT 'pending',
  `extracted_amount` DECIMAL(10,2) NULL,
  `extracted_merchant` VARCHAR(100) NULL,
  `extracted_date` DATE NULL,
  `extracted_payment_method` VARCHAR(50) NULL,
  `file_hash` VARCHAR(64) NULL,
  `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT `fk_receipts_user` FOREIGN KEY (`user_id`)
    REFERENCES `users` (`id`) ON DELETE CASCADE ON UPDATE CASCADE,
  INDEX `idx_receipts_user` (`user_id`, `created_at`),
  INDEX `idx_receipts_hash` (`user_id`, `file_hash`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 4. Expenses Table
DROP TABLE IF EXISTS `expenses`;
CREATE TABLE `expenses` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `user_id` INT NOT NULL,
  `category_id` INT NOT NULL,
  `amount` DECIMAL(10,2) NOT NULL,
  `merchant` VARCHAR(100) NOT NULL,
  `expense_date` DATE NOT NULL,
  `payment_method` ENUM('UPI', 'Cash', 'Credit Card', 'Debit Card', 'Net Banking', 'Other') NOT NULL DEFAULT 'UPI',
  `notes` TEXT NULL,
  `receipt_id` INT NULL,
  `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT `chk_expense_amount_positive` CHECK (`amount` > 0.00),
  CONSTRAINT `fk_expenses_user` FOREIGN KEY (`user_id`)
    REFERENCES `users` (`id`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `fk_expenses_category` FOREIGN KEY (`category_id`)
    REFERENCES `categories` (`id`) ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT `fk_expenses_receipt` FOREIGN KEY (`receipt_id`)
    REFERENCES `uploaded_receipts` (`id`) ON DELETE SET NULL ON UPDATE CASCADE,
  INDEX `idx_expenses_user_date` (`user_id`, `expense_date`),
  INDEX `idx_expenses_user_category` (`user_id`, `category_id`),
  INDEX `idx_expenses_merchant` (`user_id`, `merchant`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 5. Budgets Table (Supports Overall Monthly Budget and Category-Specific Limits)
DROP TABLE IF EXISTS `budgets`;
CREATE TABLE `budgets` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `user_id` INT NOT NULL,
  `category_id` INT NULL, -- NULL represents Total Monthly Budget limit
  `month` TINYINT NOT NULL,
  `year` SMALLINT NOT NULL,
  `amount` DECIMAL(10,2) NOT NULL,
  `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT `chk_budget_month` CHECK (`month` BETWEEN 1 AND 12),
  CONSTRAINT `chk_budget_year` CHECK (`year` >= 2020),
  CONSTRAINT `chk_budget_amount_positive` CHECK (`amount` > 0.00),
  CONSTRAINT `fk_budgets_user` FOREIGN KEY (`user_id`)
    REFERENCES `users` (`id`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `fk_budgets_category` FOREIGN KEY (`category_id`)
    REFERENCES `categories` (`id`) ON DELETE CASCADE ON UPDATE CASCADE,
  -- Ensure unique budget per user, category (or overall), month, and year
  -- Note: in MySQL NULL in UNIQUE constraint permits multiples if not coalesced,
  -- so we handle overall budget uniqueness with a dedicated index or application constraint.
  UNIQUE KEY `uk_user_category_month_year` (`user_id`, `category_id`, `month`, `year`),
  INDEX `idx_budgets_lookup` (`user_id`, `year`, `month`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Re-enable foreign key checks
SET FOREIGN_KEY_CHECKS = 1;

