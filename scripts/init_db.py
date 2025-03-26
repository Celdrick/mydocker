#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import mysql.connector
from mysql.connector import Error

def init_database():
    """初始化数据库和表"""
    try:
        # 从环境变量获取数据库连接信息
        host = os.environ.get('MYSQL_HOST')
        port = os.environ.get('MYSQL_PORT')
        user = os.environ.get('MYSQL_USER')
        password = os.environ.get('MYSQL_PASSWORD')
        db_name = os.environ.get('MYSQL_DB')
        
        # 首先连接到MySQL服务器，不指定数据库
        connection = mysql.connector.connect(
            host=host,
            port=port,
            user=user,
            password=password
        )
        
        if connection.is_connected():
            cursor = connection.cursor()
            
            # 创建数据库（如果不存在）
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS {db_name}")
            print(f"数据库 {db_name} 已创建或已存在")
            
            # 切换到指定数据库
            cursor.execute(f"USE {db_name}")
            
            # 创建 images_for_push 表
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS images_for_push (
                id INT AUTO_INCREMENT PRIMARY KEY,
                source_registry_url VARCHAR(255) DEFAULT 'docker.io',
                orig_name_space VARCHAR(255),
                orig_image_name VARCHAR(255),
                add_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                platform VARCHAR(50) DEFAULT 'linux/amd64',
                push_status TINYINT DEFAULT 0,
                INDEX idx_push_status (push_status),
                INDEX idx_orig_image_name (orig_image_name)
            )
            """)
            print("表 images_for_push 已创建或已存在")
            
            # 创建 pushed_images 表
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS pushed_images (
                id INT AUTO_INCREMENT PRIMARY KEY,
                source_registry_url VARCHAR(255) DEFAULT 'docker.io',
                target_registry_url VARCHAR(255),
                orig_name_space VARCHAR(255),
                orig_image_name VARCHAR(255),
                targ_name_space VARCHAR(255),
                push_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                registry_image_name VARCHAR(512),
                push_status TINYINT DEFAULT 0,
                image_size VARCHAR(50),
                digest VARCHAR(255),
                platform VARCHAR(50) DEFAULT 'linux/amd64',
                UNIQUE INDEX idx_registry_target_image (target_registry_url, registry_image_name),
                INDEX idx_orig_image_name (orig_image_name)
            )
            """)
            print("表 pushed_images 已创建或已存在")
            
    except Error as e:
        print(f"数据库连接或初始化错误: {e}")
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()
            print("MySQL连接已关闭")

if __name__ == "__main__":
    init_database()
