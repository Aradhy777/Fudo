-- =====================================================================
-- ExpenseTrack: Initial Seed Data
-- =====================================================================

USE `expensetrack`;

-- 1. Insert System Categories
INSERT INTO `categories` (`id`, `name`, `icon`, `color`, `is_system`) VALUES
(1, 'Food', 'utensils', '#10B981', TRUE),
(2, 'Travel', 'car', '#3B82F6', TRUE),
(3, 'Shopping', 'shopping-bag', '#EC4899', TRUE),
(4, 'Education', 'book-open', '#8B5CF6', TRUE),
(5, 'Entertainment', 'film', '#F59E0B', TRUE),
(6, 'Bills', 'receipt', '#EF4444', TRUE),
(7, 'Healthcare', 'heart-pulse', '#06B6D4', TRUE),
(8, 'Other', 'circle-ellipsis', '#6B7280', TRUE)
ON DUPLICATE KEY UPDATE `color`=VALUES(`color`), `icon`=VALUES(`icon`);

-- 2. Insert Demo Student Account
-- Password for demo_student is: Password123!
INSERT INTO `users` (`id`, `username`, `email`, `password_hash`, `full_name`) VALUES
(1, 'demo_student', 'student@expensetrack.edu', 'scrypt:32768:8:1$mVMnyj5NCD4ozcSV$6ca0e1ee86b98e17dc7cd5349ed8956f57ac9f342fd37d8d04dbaa81185ce9016969a1a9b79cbe95babce2547ed57c614d285fe22e997adb90a99232120d26f6', 'Aarav Sharma')
ON DUPLICATE KEY UPDATE `full_name`=VALUES(`full_name`);

-- 3. Insert Monthly Budgets for Demo Student (October 2026)
-- Overall Monthly Budget: 10,000.00
INSERT INTO `budgets` (`id`, `user_id`, `category_id`, `month`, `year`, `amount`) VALUES
(1, 1, NULL, 10, 2026, 12000.00),
(2, 1, 1, 10, 2026, 3500.00),  -- Food Budget
(3, 1, 2, 10, 2026, 1500.00),  -- Travel Budget
(4, 1, 4, 10, 2026, 2500.00),  -- Education Budget
(5, 1, 5, 10, 2026, 1200.00),  -- Entertainment Budget
(6, 1, 6, 10, 2026, 1500.00)   -- Bills Budget
ON DUPLICATE KEY UPDATE `amount`=VALUES(`amount`);

-- 4. Insert Realistic Student Expenses (Current Month: Oct 2026, plus Sep & Aug 2026 for trend charts)
INSERT INTO `expenses` (`user_id`, `category_id`, `amount`, `merchant`, `expense_date`, `payment_method`, `notes`) VALUES
-- October 2026 (Current)
(1, 1, 420.00, 'Campus Canteen', '2026-10-02', 'UPI', 'Lunch with project team'),
(1, 4, 1250.00, 'University Bookstore', '2026-10-04', 'Debit Card', 'Data Structures & Algorithms Reference Book'),
(1, 2, 280.00, 'Metro Rail Recharge', '2026-10-05', 'UPI', 'Monthly student commute card topup'),
(1, 1, 350.00, 'Domino\'s Pizza', '2026-10-08', 'UPI', 'Weekend dinner treat'),
(1, 6, 699.00, 'Jio Fiber Broadband', '2026-10-10', 'Net Banking', 'Hostel Wi-Fi split bill'),
(1, 1, 850.00, 'BigBasket Grocery', '2026-10-12', 'UPI', 'Oats, milk, fruits, and snacks'),
(1, 5, 360.00, 'PVR Cinemas', '2026-10-15', 'Credit Card', 'Movie ticket student discount'),
(1, 2, 180.00, 'Uber Auto', '2026-10-18', 'UPI', 'Ride to university library'),
(1, 1, 550.00, 'Cafe Coffee Day', '2026-10-21', 'UPI', 'Study session coffee & brownie'),
(1, 3, 1199.00, 'Decathlon', '2026-10-24', 'UPI', 'Gym water bottle & training resistance bands'),
(1, 1, 680.00, 'Subway', '2026-10-26', 'UPI', 'Dinner combo after lab exam'),
(1, 7, 240.00, 'Apollo Pharmacy', '2026-10-27', 'Cash', 'Vitamins & cold medicine'),

-- September 2026 (Previous Month for History & Trend Charts)
(1, 1, 3100.00, 'Mess & Canteen', '2026-09-05', 'UPI', 'Monthly hostel food mess payment'),
(1, 4, 1800.00, 'Coursera Learning', '2026-09-12', 'Credit Card', 'Cloud Computing Specialization course'),
(1, 2, 950.00, 'Metro & Bus Pass', '2026-09-15', 'UPI', 'Monthly transport pass'),
(1, 6, 750.00, 'Mobile Postpaid Bill', '2026-09-18', 'UPI', 'Airtel monthly plan'),
(1, 5, 850.00, 'Gaming Arena & Movies', '2026-09-22', 'UPI', 'Weekend hangout'),
(1, 3, 2100.00, 'Amazon India', '2026-09-26', 'Debit Card', 'Wireless mouse and ergonomic keyboard'),

-- August 2026
(1, 4, 3500.00, 'University Semester Fee', '2026-08-05', 'Net Banking', 'Lab and library subscription fees'),
(1, 1, 2800.00, 'Hostel Mess', '2026-08-10', 'UPI', 'Mess meal charges'),
(1, 2, 800.00, 'City Bus Transport', '2026-08-14', 'Cash', 'Bus passes'),
(1, 6, 700.00, 'Broadband Internet', '2026-08-20', 'UPI', 'Monthly internet bill');

