"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { cn } from "@/lib/utils";

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const from = searchParams.get("from") ?? "/";

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      const res = await fetch("/api/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });

      if (!res.ok) {
        const data = (await res.json()) as { error?: string };
        setError(data.error ?? "登录失败");
        return;
      }

      router.push(from);
      router.refresh();
    } catch {
      setError("网络错误，请重试");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background">
      <div className="w-full max-w-sm space-y-6 rounded-2xl border bg-card p-8 shadow-sm">
        {/* Logo / 标题 */}
        <div className="space-y-1 text-center">
          <h1 className="text-2xl font-semibold tracking-tight">DeerFlow</h1>
          <p className="text-sm text-muted-foreground">请登录以继续</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1">
            <label className="text-sm font-medium" htmlFor="username">
              用户名
            </label>
            <input
              id="username"
              type="text"
              autoComplete="username"
              required
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className={cn(
                "w-full rounded-lg border bg-background px-3 py-2 text-sm outline-none",
                "placeholder:text-muted-foreground",
                "focus:ring-2 focus:ring-ring focus:ring-offset-1",
                "transition-shadow",
              )}
              placeholder="请输入用户名"
            />
          </div>

          <div className="space-y-1">
            <label className="text-sm font-medium" htmlFor="password">
              密码
            </label>
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className={cn(
                "w-full rounded-lg border bg-background px-3 py-2 text-sm outline-none",
                "placeholder:text-muted-foreground",
                "focus:ring-2 focus:ring-ring focus:ring-offset-1",
                "transition-shadow",
              )}
              placeholder="请输入密码"
            />
          </div>

          {error && (
            <p className="rounded-lg bg-destructive/10 px-3 py-2 text-sm text-destructive">
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={loading}
            className={cn(
              "w-full rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground",
              "hover:bg-primary/90 active:scale-[0.98]",
              "transition-all duration-150",
              "disabled:cursor-not-allowed disabled:opacity-50",
            )}
          >
            {loading ? "登录中..." : "登录"}
          </button>
        </form>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  );
}
