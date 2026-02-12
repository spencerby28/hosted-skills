---
name: cloudflare-better-auth-d1
description: |
  Set up Better Auth with email/password on Cloudflare Workers + D1. Framework-agnostic setup
  for Hono, Elysia, SvelteKit, or bare Workers. Use when: (1) adding auth to a new Cloudflare
  Workers project, (2) need email/password auth with D1 SQLite, (3) setting up Better Auth
  on edge runtime. Assumes already authenticated with wrangler.
---

# Cloudflare Workers + Better Auth + D1 Setup

Framework-agnostic guide for email/password authentication on Cloudflare Workers.

## Prerequisites

```bash
# Must be logged in
bunx wrangler whoami

# If not logged in:
bunx wrangler login
```

## 1. Create D1 Database

```bash
# Create the database
bunx wrangler d1 create my-app-db

# Note the database_id from output - you'll need it
```

## 2. Wrangler Configuration

**wrangler.jsonc** (or wrangler.toml):
```jsonc
{
  "$schema": "./node_modules/wrangler/config-schema.json",
  "name": "my-app",
  "compatibility_date": "2026-01-14",
  "compatibility_flags": ["nodejs_compat"],
  "main": "src/index.ts",
  "d1_databases": [
    {
      "binding": "DB",
      "database_name": "my-app-db",
      "database_id": "YOUR_DATABASE_ID_HERE",
      "migrations_dir": "drizzle"
    }
  ],
  "vars": {
    "BETTER_AUTH_URL": "http://localhost:8787"
  }
}
```

**Key flags:**
- `nodejs_compat` - Required for Better Auth's crypto operations
- `migrations_dir` - Points to your Drizzle migrations folder

## 3. Install Dependencies

```bash
bun add better-auth drizzle-orm
bun add -D drizzle-kit wrangler @cloudflare/workers-types
```

## 4. TypeScript Types

**src/env.d.ts** or **worker-configuration.d.ts**:
```typescript
interface Env {
  DB: D1Database;
  BETTER_AUTH_SECRET: string;
  BETTER_AUTH_URL?: string;
}
```

## 5. Database Schema (Drizzle)

**src/db/schema.ts**:
```typescript
import { sqliteTable, text, integer } from "drizzle-orm/sqlite-core";

export const user = sqliteTable("user", {
  id: text("id").primaryKey(),
  name: text("name").notNull(),
  email: text("email").notNull().unique(),
  emailVerified: integer("email_verified", { mode: "boolean" }).notNull(),
  image: text("image"),
  createdAt: integer("created_at", { mode: "timestamp" }).notNull(),
  updatedAt: integer("updated_at", { mode: "timestamp" }).notNull()
});

export const session = sqliteTable("session", {
  id: text("id").primaryKey(),
  expiresAt: integer("expires_at", { mode: "timestamp" }).notNull(),
  token: text("token").notNull().unique(),
  createdAt: integer("created_at", { mode: "timestamp" }).notNull(),
  updatedAt: integer("updated_at", { mode: "timestamp" }).notNull(),
  ipAddress: text("ip_address"),
  userAgent: text("user_agent"),
  userId: text("user_id").notNull().references(() => user.id)
});

export const account = sqliteTable("account", {
  id: text("id").primaryKey(),
  accountId: text("account_id").notNull(),
  providerId: text("provider_id").notNull(),
  userId: text("user_id").notNull().references(() => user.id),
  accessToken: text("access_token"),
  refreshToken: text("refresh_token"),
  idToken: text("id_token"),
  accessTokenExpiresAt: integer("access_token_expires_at", { mode: "timestamp" }),
  refreshTokenExpiresAt: integer("refresh_token_expires_at", { mode: "timestamp" }),
  scope: text("scope"),
  password: text("password"),
  createdAt: integer("created_at", { mode: "timestamp" }).notNull(),
  updatedAt: integer("updated_at", { mode: "timestamp" }).notNull()
});

export const verification = sqliteTable("verification", {
  id: text("id").primaryKey(),
  identifier: text("identifier").notNull(),
  value: text("value").notNull(),
  expiresAt: integer("expires_at", { mode: "timestamp" }).notNull(),
  createdAt: integer("created_at", { mode: "timestamp" }),
  updatedAt: integer("updated_at", { mode: "timestamp" })
});
```

## 6. Initial Migration

**drizzle/0000_init.sql**:
```sql
CREATE TABLE IF NOT EXISTS "user" (
  "id" text PRIMARY KEY NOT NULL,
  "name" text NOT NULL,
  "email" text NOT NULL,
  "email_verified" integer NOT NULL,
  "image" text,
  "created_at" integer NOT NULL,
  "updated_at" integer NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS "user_email_unique" ON "user" ("email");

CREATE TABLE IF NOT EXISTS "session" (
  "id" text PRIMARY KEY NOT NULL,
  "expires_at" integer NOT NULL,
  "token" text NOT NULL,
  "created_at" integer NOT NULL,
  "updated_at" integer NOT NULL,
  "ip_address" text,
  "user_agent" text,
  "user_id" text NOT NULL REFERENCES "user"("id")
);

CREATE UNIQUE INDEX IF NOT EXISTS "session_token_unique" ON "session" ("token");

CREATE TABLE IF NOT EXISTS "account" (
  "id" text PRIMARY KEY NOT NULL,
  "account_id" text NOT NULL,
  "provider_id" text NOT NULL,
  "user_id" text NOT NULL REFERENCES "user"("id"),
  "access_token" text,
  "refresh_token" text,
  "id_token" text,
  "access_token_expires_at" integer,
  "refresh_token_expires_at" integer,
  "scope" text,
  "password" text,
  "created_at" integer NOT NULL,
  "updated_at" integer NOT NULL
);

CREATE TABLE IF NOT EXISTS "verification" (
  "id" text PRIMARY KEY NOT NULL,
  "identifier" text NOT NULL,
  "value" text NOT NULL,
  "expires_at" integer NOT NULL,
  "created_at" integer,
  "updated_at" integer
);
```

## 7. Better Auth Configuration

**src/auth.ts**:
```typescript
import { betterAuth } from "better-auth";
import { drizzleAdapter } from "better-auth/adapters/drizzle";
import { drizzle } from "drizzle-orm/d1";
import * as schema from "./db/schema";

export function createAuth(env: Env) {
  const db = drizzle(env.DB, { schema });

  // CRITICAL: Build trusted origins dynamically
  const trustedOrigins = new Set([
    "http://localhost:8787",
    "http://localhost:5173",
    "http://localhost:4173",
  ]);

  // Add production URL if set
  if (env.BETTER_AUTH_URL) {
    trustedOrigins.add(env.BETTER_AUTH_URL);
  }

  return betterAuth({
    secret: env.BETTER_AUTH_SECRET,
    baseURL: env.BETTER_AUTH_URL || "http://localhost:8787",
    database: drizzleAdapter(db, {
      provider: "sqlite",
      schema
    }),
    emailAndPassword: {
      enabled: true
    },
    trustedOrigins: Array.from(trustedOrigins),
  });
}

export type Auth = ReturnType<typeof createAuth>;
```

## 8. Framework Integration

### Bare Cloudflare Workers

```typescript
// src/index.ts
import { createAuth } from "./auth";

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    // Handle auth routes
    if (url.pathname.startsWith("/api/auth")) {
      const auth = createAuth(env);
      return auth.handler(request);
    }

    // Your other routes...
    return new Response("Hello World");
  }
};
```

### Hono

```typescript
import { Hono } from "hono";
import { createAuth } from "./auth";

const app = new Hono<{ Bindings: Env }>();

// Mount Better Auth
app.on(["GET", "POST"], "/api/auth/*", (c) => {
  const auth = createAuth(c.env);
  return auth.handler(c.req.raw);
});

// Protected route example
app.get("/api/me", async (c) => {
  const auth = createAuth(c.env);
  const session = await auth.api.getSession({
    headers: c.req.raw.headers,
  });

  if (!session) {
    return c.json({ error: "Unauthorized" }, 401);
  }

  return c.json({ user: session.user });
});

export default app;
```

### Elysia

```typescript
import { Elysia } from "elysia";
import { createAuth } from "./auth";

const app = new Elysia()
  .all("/api/auth/*", ({ request, env }) => {
    const auth = createAuth(env);
    return auth.handler(request);
  });

export default app;
```

## 9. Client-Side Auth

**For any frontend:**
```typescript
import { createAuthClient } from "better-auth/client";

export const authClient = createAuthClient({
  baseURL: window.location.origin, // or your API URL
});

// Sign up
await authClient.signUp.email({
  email: "user@example.com",
  password: "securepassword",
  name: "User Name",
});

// Sign in
await authClient.signIn.email({
  email: "user@example.com",
  password: "securepassword",
});

// Sign out
await authClient.signOut();

// Get session
const session = await authClient.getSession();
```

## 10. Environment Setup

### Local Development

**.dev.vars** (gitignored):
```
BETTER_AUTH_SECRET=your-secret-here-generate-with-openssl
```

Generate secret:
```bash
openssl rand -base64 32
```

### Production

```bash
# Set the secret
bunx wrangler secret put BETTER_AUTH_SECRET
# Enter your secret when prompted

# Set the production URL (optional, can use vars in wrangler.jsonc)
bunx wrangler secret put BETTER_AUTH_URL
# Enter: https://your-app.your-domain.com
```

## 11. Database Migrations

```bash
# Apply to local D1 emulator
bunx wrangler d1 migrations apply DB --local

# Apply to production
bunx wrangler d1 migrations apply DB --remote
```

## 12. Deploy

```bash
bunx wrangler deploy
```

## Common Gotchas

### 1. "crypto is not defined"
Add `nodejs_compat` to compatibility_flags in wrangler.jsonc.

### 2. CORS errors on auth endpoints
Ensure `trustedOrigins` includes your frontend URL. Better Auth validates the Origin header.

### 3. Session not persisting
Check that cookies are being set with correct domain. For local dev, ensure you're accessing via `localhost` not `127.0.0.1`.

### 4. "BETTER_AUTH_SECRET must be set"
- Local: Create `.dev.vars` file with the secret
- Production: Run `wrangler secret put BETTER_AUTH_SECRET`

### 5. D1 "no such table" errors
Run migrations:
```bash
bunx wrangler d1 migrations apply DB --local  # for dev
bunx wrangler d1 migrations apply DB --remote # for prod
```

### 6. Wrangler operating on local instead of remote
Always use `--remote` flag for production D1 operations:
```bash
bunx wrangler d1 execute DB --remote --command "SELECT * FROM user"
```

## Drizzle Config (Optional)

**drizzle.config.ts** - for `drizzle-kit generate`:
```typescript
import { defineConfig } from "drizzle-kit";

export default defineConfig({
  schema: "./src/db/schema.ts",
  out: "./drizzle",
  dialect: "sqlite",
  driver: "d1-http",
  dbCredentials: {
    accountId: process.env.CLOUDFLARE_ACCOUNT_ID || "",
    databaseId: process.env.CLOUDFLARE_DATABASE_ID || "",
    token: process.env.CLOUDFLARE_D1_TOKEN || "",
  },
});
```

## Quick Start Checklist

- [ ] `bunx wrangler login` (if not already)
- [ ] `bunx wrangler d1 create my-app-db`
- [ ] Update `wrangler.jsonc` with database_id
- [ ] `bun add better-auth drizzle-orm`
- [ ] Create schema files (copy from above)
- [ ] Create `drizzle/0000_init.sql` migration
- [ ] Create `.dev.vars` with `BETTER_AUTH_SECRET`
- [ ] `bunx wrangler d1 migrations apply DB --local`
- [ ] Wire up auth routes in your framework
- [ ] Test locally: `bunx wrangler dev`
- [ ] `bunx wrangler secret put BETTER_AUTH_SECRET`
- [ ] `bunx wrangler d1 migrations apply DB --remote`
- [ ] `bunx wrangler deploy`
