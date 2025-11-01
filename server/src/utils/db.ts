import * as fs from 'fs';
import * as path from 'path';
import type { User, Strategy } from '../types';

const DATA_DIR = path.join(__dirname, '../../data');

// 确保数据目录存在
if (!fs.existsSync(DATA_DIR)) {
  fs.mkdirSync(DATA_DIR, { recursive: true });
}

const USERS_FILE = path.join(DATA_DIR, 'users.json');
const STRATEGIES_FILE = path.join(DATA_DIR, 'strategies.json');

// 初始化数据文件
function initFile(filePath: string, defaultValue: unknown[]): void {
  if (!fs.existsSync(filePath)) {
    fs.writeFileSync(filePath, JSON.stringify(defaultValue, null, 2), 'utf-8');
  }
}

initFile(USERS_FILE, []);
initFile(STRATEGIES_FILE, []);

export const db = {
  users: {
    getAll(): User[] {
      try {
        const content = fs.readFileSync(USERS_FILE, 'utf-8');
        return JSON.parse(content) as User[];
      } catch {
        return [];
      }
    },

    save(users: User[]): void {
      fs.writeFileSync(USERS_FILE, JSON.stringify(users, null, 2), 'utf-8');
    },

    findById(id: string): User | undefined {
      return this.getAll().find((u) => u.id === id);
    },

    findByEmail(email: string): User | undefined {
      return this.getAll().find((u) => u.email === email);
    },

    create(user: User): User {
      const users = this.getAll();
      users.push(user);
      this.save(users);
      return user;
    },

    update(id: string, updates: Partial<User>): User | null {
      const users = this.getAll();
      const index = users.findIndex((u) => u.id === id);
      if (index === -1) return null;
      users[index] = { ...users[index], ...updates, updatedAt: new Date().toISOString() };
      this.save(users);
      return users[index];
    },
  },

  strategies: {
    getAll(): Strategy[] {
      try {
        const content = fs.readFileSync(STRATEGIES_FILE, 'utf-8');
        return JSON.parse(content) as Strategy[];
      } catch {
        return [];
      }
    },

    save(strategies: Strategy[]): void {
      fs.writeFileSync(STRATEGIES_FILE, JSON.stringify(strategies, null, 2), 'utf-8');
    },

    findById(id: string): Strategy | undefined {
      return this.getAll().find((s) => s.id === id);
    },

    findByUserId(userId: string): Strategy[] {
      return this.getAll().filter((s) => s.userId === userId);
    },

    create(strategy: Strategy): Strategy {
      const strategies = this.getAll();
      strategies.push(strategy);
      this.save(strategies);
      return strategy;
    },

    update(id: string, updates: Partial<Strategy>): Strategy | null {
      const strategies = this.getAll();
      const index = strategies.findIndex((s) => s.id === id);
      if (index === -1) return null;
      strategies[index] = { ...strategies[index], ...updates, updatedAt: new Date().toISOString() };
      this.save(strategies);
      return strategies[index];
    },

    delete(id: string): boolean {
      const strategies = this.getAll();
      const index = strategies.findIndex((s) => s.id === id);
      if (index === -1) return false;
      strategies.splice(index, 1);
      this.save(strategies);
      return true;
    },
  },
};

