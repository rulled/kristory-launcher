"use client"

import { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useToast } from "@/hooks/use-toast";
import { API_BASE_URL } from "@/app/page";
import { Loader2 } from "lucide-react";

type AddAccountDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onAccountAdded: () => void;
};

export function AddAccountDialog({ open, onOpenChange, onAccountAdded }: AddAccountDialogProps) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const { toast } = useToast();

  const handleAddAccount = async () => {
    if (isLoading || !email || !password) return;
    setIsLoading(true);
    try {
        const response = await fetch(`${API_BASE_URL}/api/auth/elyby`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, password }),
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || 'Не удалось добавить аккаунт');
        }

        toast({ title: "Успех", description: `Аккаунт ${data.username} добавлен.` });
        onAccountAdded();
        onOpenChange(false);
        setEmail("");
        setPassword("");
    } catch (error: any) {
        console.error("Add account error:", error);
        toast({ title: "Ошибка", description: error.message, variant: "destructive" });
    } finally {
        setIsLoading(false);
    }
  };
  
  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    handleAddAccount();
  }

  const handleOpenChange = (open: boolean) => {
    if (!open) {
      setEmail("");
      setPassword("");
      setIsLoading(false);
    }
    onOpenChange(open);
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-[425px] bg-card border-border">
        <DialogHeader>
          <DialogTitle>Вход через Ely.by</DialogTitle>
          <DialogDescription>
            Введите данные вашего аккаунта Ely.by.
            <div className="mt-1">
              Нет аккаунта?{' '}
              <a 
                href="https://account.ely.by/register" 
                target="_blank" 
                rel="noopener noreferrer" 
                className="text-primary underline hover:text-primary/80"
                onClick={(e) => e.stopPropagation()} // Prevent dialog from closing
              >
                Зарегистрируйтесь
              </a>
            </div>
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit}>
          <div className="grid gap-4 py-4">
            <div className="grid grid-cols-4 items-center gap-4">
              <Label htmlFor="email" className="text-right">
                Email
              </Label>
              <Input 
                id="email" 
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="user@example.com"
                className="col-span-3" 
                required
              />
            </div>
            <div className="grid grid-cols-4 items-center gap-4">
              <Label htmlFor="password" className="text-right">
                Пароль
              </Label>
              <Input 
                id="password" 
                type="password" 
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="col-span-3" 
                required
              />
            </div>
          </div>
          <DialogFooter>
            <Button type="submit" disabled={isLoading || !email || !password}>
              {isLoading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Войти
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
