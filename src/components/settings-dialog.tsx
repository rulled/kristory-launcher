
"use client"

import { useState, useEffect, useCallback } from "react"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Slider } from "@/components/ui/slider"
import { Switch } from "@/components/ui/switch"
import { Coffee, FileText, Folder, Gamepad2, Loader2, Plus, Terminal, Trash2, Users, Wrench } from "lucide-react"
import { AddAccountDialog } from "./add-account-dialog"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Account, API_BASE_URL, LauncherStatus, GameSettings } from "@/app/page"
import { useToast } from "@/hooks/use-toast"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"

// --- Расширяем типы для Electron API и LauncherStatus ---
declare global {
  interface Window {
    electronAPI: {
      minimizeWindow: () => void;
      selectFile: (options: any) => Promise<string | null>;
      selectDirectory: (options: any) => Promise<string | null>;
      openLogsFolder: () => void;
      restartApp: () => void;
      onUpdateMessage: (callback: (message: string) => void) => void;
      onUpdateDownloaded: (callback: () => void) => void;
      removeAllListeners: () => void;
      getLauncherVersion: () => Promise<string>;
    };
  }
}

type LauncherStatusWithBuild = LauncherStatus & { build_tag?: string };

type Mod = {
  filename: string;
  name: string;
  description: string;
  status: 'enabled' | 'disabled';
}

type JavaSettings = {
    path: string;
    min_mem: number;
    max_mem: number;
}

type SettingsDialogProps = { 
    children: React.ReactNode, 
    onSettingsChange: () => void, 
    launcherStatus: LauncherStatus,
    open: boolean;
    onOpenChange: (open: boolean) => void;
}

export function SettingsDialog({ children, onSettingsChange, launcherStatus, open, onOpenChange }: SettingsDialogProps) {
  const launcherStatusTyped = launcherStatus as LauncherStatusWithBuild;
  const [addAccountOpen, setAddAccountOpen] = useState(false);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [mods, setMods] = useState<Mod[]>([]);
  const [javaSettings, setJavaSettings] = useState<JavaSettings>({ path: "", min_mem: 1024, max_mem: 4096 });
  const [initialGameSettings, setInitialGameSettings] = useState<GameSettings>({ server_address: "", enable_logs: false, game_directory: "" });
  const [gameSettings, setGameSettings] = useState<GameSettings>({ server_address: "", enable_logs: false, game_directory: "" });
  const [maxSystemRam, setMaxSystemRam] = useState(8192); // Default to 8GB
  const [showJavaList, setShowJavaList] = useState(false);
  const [javaList, setJavaList] = useState<{ path: string; version: string; is_in_path: boolean }[]>([]);
  const [isLoadingJavaList, setIsLoadingJavaList] = useState(false);
  const [launcherVersion, setLauncherVersion] = useState<string>("...");
  
  const { toast } = useToast();

  const isProcessing = launcherStatus.is_processing;

  const fetchSystemInfo = useCallback(async () => {
    try {
        const res = await fetch(`${API_BASE_URL}/api/system-info`);
        if (res.ok) {
            const data = await res.json();
            // Reserve 20% of RAM for the system
            const availableRam = Math.floor(data.total_ram_mb * 0.8);
            setMaxSystemRam(availableRam);
        }
    } catch (error) {
        console.error("Failed to fetch system info:", error);
        // Keep a reasonable default on error
        setMaxSystemRam(8192);
    }
  }, []);


  const fetchData = useCallback(async () => {
    try {
        const [accRes, modsRes, configRes] = await Promise.all([
            fetch(`${API_BASE_URL}/api/accounts`),
            fetch(`${API_BASE_URL}/api/mods`),
            fetch(`${API_BASE_URL}/api/config`),
        ]);
        setAccounts(await accRes.json());
        setMods(await modsRes.json());
        const config = await configRes.json();
        if (config.java_settings) {
            setJavaSettings(config.java_settings);
        }
        if (config.game_settings) {
            setGameSettings(config.game_settings);
            setInitialGameSettings(config.game_settings);
        }
    } catch (error) {
        console.error("Failed to fetch settings data:", error);
        toast({ title: "Ошибка", description: "Не удалось загрузить данные настроек.", variant: "destructive" });
    }
  }, [toast]);

  const fetchJavaList = async () => {
    setIsLoadingJavaList(true);
    try {
      const res = await fetch(`${API_BASE_URL}/api/java/list`);
      const data = await res.json();
      setJavaList(data);
    } catch (e) {
      toast({ title: "Ошибка", description: "Не удалось получить список Java.", variant: "destructive" });
    } finally {
      setIsLoadingJavaList(false);
    }
  };

  const handleShowJavaList = () => {
    setShowJavaList((prev) => !prev);
    if (!showJavaList) fetchJavaList();
  };

  const handleChooseJava = (path: string) => {
    setJavaSettings({ ...javaSettings, path });
    handleSaveSettings('java_settings', { ...javaSettings, path });
    toast({ title: "Java выбрана", description: path });
    setShowJavaList(false);
  };

  useEffect(() => {
    if (open) {
        fetchData();
        fetchSystemInfo();
        // Получаем версию лаунчера
        if (window.electronAPI?.getLauncherVersion) {
          window.electronAPI.getLauncherVersion().then(setLauncherVersion);
        }
    }
  }, [open, fetchData, fetchSystemInfo]);

  const handleAddAccount = () => {
    fetchData(); // Refresh accounts list
    onSettingsChange(); // Notify parent
  }

  const handleDeleteAccount = async (uuid: string) => {
    try {
        const res = await fetch(`${API_BASE_URL}/api/accounts/${uuid}`, { method: 'DELETE' });
        if (!res.ok) throw new Error("Failed to delete account");
        toast({ title: "Успех", description: "Аккаунт удален." });
        fetchData();
        onSettingsChange();
    } catch (error) {
        toast({ title: "Ошибка", description: "Не удалось удалить аккаунт.", variant: "destructive" });
    }
  }

  const handleToggleMod = async (filename: string, enabled: boolean) => {
    const originalMods = mods;
    setMods(mods.map(m => m.filename === filename ? { ...m, status: enabled ? 'enabled' : 'disabled' } : m));
    try {
        const res = await fetch(`${API_BASE_URL}/api/mods/state`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ filename, enable: enabled })
        });
        if (!res.ok) throw new Error("Failed to toggle mod");
    } catch (error) {
        setMods(originalMods);
        toast({ title: "Ошибка", description: `Не удалось изменить статус мода.`, variant: "destructive" });
    }
  }

  const handleSaveSettings = async (settingsKey: 'java_settings' | 'game_settings', settingsData: any) => {
     try {
        const res = await fetch(`${API_BASE_URL}/api/config`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ [settingsKey]: settingsData })
        });
        if (!res.ok) throw new Error(`Failed to save ${settingsKey}`);
        
        // Если сохраняем game_settings с game_directory, ждём подтверждения от backend
        if (settingsKey === 'game_settings' && settingsData.game_directory) {
          let updated = false;
          for (let i = 0; i < 5; i++) {
            const configRes = await fetch(`${API_BASE_URL}/api/config`);
            if (configRes.ok) {
              const config = await configRes.json();
              if (config?.game_settings?.game_directory === settingsData.game_directory) {
                updated = true;
                break;
              }
            }
            await new Promise(r => setTimeout(r, 200));
          }
          if (!updated) throw new Error("Backend не подтвердил обновление пути к папке");
        }
        
        toast({ title: "Успех", description: "Настройки сохранены." });

        if (settingsKey === 'game_settings' && settingsData.enable_logs !== initialGameSettings.enable_logs) {
            toast({
                title: "Требуется перезапуск",
                description: "Настройки логов будут применены после перезапуска лаунчера.",
                duration: 5000,
            });
        }
        
        onSettingsChange(); // Notify main page of config changes
    } catch (error) {
        toast({ title: "Ошибка", description: "Не удалось сохранить настройки.", variant: "destructive" });
    }
  }

  const handleReinstallClick = async () => {
    if (isProcessing) return;
    try {
      const res = await fetch(`${API_BASE_URL}/api/verify-files`, { method: 'POST' });
      if (!res.ok) throw new Error("Failed to start verification");
      toast({ title: "Процесс запущен", description: "Проверка и установка файлов началась в фоновом режиме." });
      onOpenChange(false);
    } catch (error) {
      toast({ title: "Ошибка", description: "Не удалось запустить проверку файлов.", variant: "destructive" });
    }
  };

  const handleSelectJavaPath = async () => {
    if (window.electronAPI) {
        const path = await window.electronAPI.selectFile({
            title: 'Выберите исполняемый файл javaw.exe',
            filters: [
                { name: 'Java Executable (javaw.exe)', extensions: ['exe'] },
                { name: 'Все файлы', extensions: ['*'] }
            ]
        });
        if (path) {
            setJavaSettings({ ...javaSettings, path });
            handleSaveSettings('java_settings', { ...javaSettings, path });
        }
    }
  };

  const handleSelectGameDirectory = async () => {
    if (window.electronAPI) {
        const path = await window.electronAPI.selectDirectory({
            title: 'Выберите папку для установки игры',
        });
        if (path) {
            // Добавляем подпапку, если её нет
            let finalPath = path;
            if (!/([\\/]|^)Kristory Client([\\/]|$)/i.test(path)) {
              finalPath = path.replace(/[\\/]+$/, '') + (path.endsWith('\\') || path.endsWith('/') ? '' : (path.includes('\\') ? '\\' : '/')) + 'Kristory Client';
            }
            setGameSettings({ ...gameSettings, game_directory: finalPath });
            // Ждём подтверждения сохранения перед обновлением состояния
            await handleSaveSettings('game_settings', { ...gameSettings, game_directory: finalPath });
        }
    }
  };

  const handleOpenLogsFolder = () => {
      if (window.electronAPI) {
          window.electronAPI.openLogsFolder();
      }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogTrigger asChild>{children}</DialogTrigger>
      <DialogContent className="max-w-[380px] h-[600px] flex flex-col bg-card border-border rounded-3xl">
        <DialogHeader>
          <DialogTitle>Настройки</DialogTitle>
          <DialogDescription>
            Управляйте настройками игры, аккаунтами и модами.
          </DialogDescription>
        </DialogHeader>
        <Tabs defaultValue="game" className="flex-1 flex flex-col overflow-hidden">
          <TabsList className="grid w-full grid-cols-5 items-center bg-transparent p-0 shrink-0">
            <TabsTrigger value="game" className="flex-col h-auto gap-1"><Gamepad2 className="h-5 w-5" /><span className="text-xs">Игра</span></TabsTrigger>
            <TabsTrigger value="accounts" className="flex-col h-auto gap-1"><Users className="h-5 w-5" /><span className="text-xs">Аккаунты</span></TabsTrigger>
            <TabsTrigger value="java" className="flex-col h-auto gap-1"><Coffee className="h-5 w-5" /><span className="text-xs">Java</span></TabsTrigger>
            <TabsTrigger value="mods" className="flex-col h-auto gap-1"><Wrench className="h-5 w-5" /><span className="text-xs">Моды</span></TabsTrigger>
            <TabsTrigger value="debug" className="flex-col h-auto gap-1"><Terminal className="h-5 w-5" /><span className="text-xs">Отладка</span></TabsTrigger>
          </TabsList>
          
          <ScrollArea className="flex-1 mt-4">
            <div className="pr-4">
              <TabsContent value="game" className="mt-0">
                  <div className="flex flex-col space-y-4 p-1">
                      <div className="space-y-2">
                          <Label htmlFor="game-directory">Папка игры</Label>
                          <div className="flex items-center space-x-2">
                            <Input id="game-directory" value={gameSettings.game_directory} readOnly placeholder="Папка для игры не выбрана" className="flex-grow text-xs" />
                            <Button variant="outline" onClick={handleSelectGameDirectory}>Изменить</Button>
                          </div>
                      </div>

                      <hr className="border-border my-4"/>

                      <h3 className="font-semibold pt-2">О лаунчере и сборке</h3>
                      <div className="flex items-center justify-between p-3 rounded-md bg-secondary">
                          <span>Версия лаунчера:</span>
                          <span className="font-mono bg-muted px-2 py-1 rounded-md">{launcherVersion}</span>
                      </div>
                      <div className="flex items-center justify-between p-3 rounded-md bg-secondary">
                          <span>Версия сборки:</span>
                          <span className="font-mono bg-muted px-2 py-1 rounded-md">{launcherStatusTyped.build_tag || "N/A"}</span>
                      </div>
                      <div className="space-y-2 !mt-6">
                        <Button variant="outline" className="w-full" onClick={handleReinstallClick} disabled={isProcessing || !gameSettings.game_directory}>
                          {isProcessing ? ( <><Loader2 className="mr-2 h-4 w-4 animate-spin" /><span>Выполняется...</span></>) 
                          : (<><FileText className="mr-2 h-4 w-4"/><span>Переустановить/Проверить файлы</span></>)}
                        </Button>
                      </div>
                  </div>
              </TabsContent>

              <TabsContent value="accounts" className="mt-0">
                <div className="flex flex-col">
                  <div className="flex justify-between items-center mb-4 px-1">
                    <h3 className="font-semibold">Аккаунты</h3>
                    <Button variant="ghost" size="sm" onClick={() => setAddAccountOpen(true)}><Plus className="mr-2 h-4 w-4" /> Добавить</Button>
                  </div>
                  <div className="space-y-2">
                    {accounts.map((acc) => (
                      <div key={acc.uuid} className="flex items-center justify-between p-2 rounded-md bg-secondary">
                        <span className="truncate pr-2">{acc.username}</span>
                        <Button variant="ghost" size="icon" className="text-muted-foreground hover:text-destructive h-6 w-6 flex-shrink-0" onClick={() => handleDeleteAccount(acc.uuid)}>
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>
                    ))}
                    {accounts.length === 0 && <p className="text-center text-sm text-muted-foreground p-4">Аккаунтов нет</p>}
                  </div>
                </div>
              </TabsContent>

              <TabsContent value="java" className="mt-0">
                  <div className="flex flex-col space-y-6 p-1">
                      <div>
                          <Label>Путь к Java</Label>
                           <div className="flex items-center space-x-2 mt-2">
                                <Input 
                                    id="java-path" 
                                    value={javaSettings.path} 
                                    readOnly 
                                    placeholder="Автоматически" 
                                    className="flex-grow text-xs" 
                                />
                                <Button variant="outline" onClick={handleSelectJavaPath}>Обзор...</Button>
                           </div>
                          <Button variant="secondary" className="mt-2 w-full" onClick={handleShowJavaList}>
                            {showJavaList ? "Скрыть найденные Java" : "Показать найденные Java"}
                          </Button>
                          {showJavaList && (
                            <ScrollArea className="mt-3 max-h-80 border rounded-lg bg-secondary p-2" style={{ maxHeight: 320 }}>
                              {isLoadingJavaList ? (
                                <div className="text-center text-muted-foreground py-4">Загрузка...</div>
                              ) : javaList.length === 0 ? (
                                <div className="text-center text-muted-foreground py-4">Java не найдены</div>
                              ) : (
                                javaList.map((j) => (
                                  <div key={j.path} className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b last:border-b-0 py-2">
                                    <div className="flex-1 min-w-0">
                                      <div className="font-mono text-xs break-all">{j.path}</div>
                                      <div className="text-xs text-muted-foreground">{j.version}</div>
                                      {j.is_in_path && <span className="text-green-500 text-xs">[PATH]</span>}
                                    </div>
                                    <Button size="sm" variant="outline" onClick={() => handleChooseJava(j.path)}>Выбрать</Button>
                                  </div>
                                ))
                              )}
                            </ScrollArea>
                          )}
                      </div>
                       <div>
                          <Label>Выделение RAM</Label>
                          <div className="flex items-center justify-between text-sm text-muted-foreground mt-2">
                              <span>{javaSettings.min_mem} MB</span>
                              <span>{javaSettings.max_mem} MB</span>
                          </div>
                          <Slider
                              min={512} max={maxSystemRam} step={512}
                              value={[javaSettings.min_mem, javaSettings.max_mem]}
                              onValueChange={(val) => setJavaSettings({...javaSettings, min_mem: val[0], max_mem: val[1]})}
                              className="mt-2"
                          />
                      </div>
                      <Button onClick={() => handleSaveSettings('java_settings', javaSettings)}>Сохранить настройки Java</Button>
                  </div>
              </TabsContent>

              <TabsContent value="mods" className="mt-0">
                <TooltipProvider delayDuration={100}>
                    <div className="space-y-2">
                        {mods.length > 0 ? mods.map((mod) => (
                            <div key={mod.filename} className="flex min-h-14 items-center justify-between gap-4 rounded-md bg-secondary p-3">
                                <Tooltip>
                                    <TooltipTrigger asChild>
                                        <Label htmlFor={`mod-${mod.filename}`} className="cursor-help break-all">
                                            {mod.name}
                                        </Label>
                                    </TooltipTrigger>
                                    <TooltipContent side="top" align="start">
                                        <p className="max-w-xs">{mod.description || "Нет описания"}</p>
                                    </TooltipContent>
                                </Tooltip>
                                <Switch id={`mod-${mod.filename}`} checked={mod.status === 'enabled'} onCheckedChange={(checked) => handleToggleMod(mod.filename, checked)} />
                            </div>
                        )) : <p className="text-center text-sm text-muted-foreground p-4">Управляемые моды не найдены или папка игры не выбрана.</p>}
                    </div>
                </TooltipProvider>
              </TabsContent>

               <TabsContent value="debug" className="mt-0">
                  <div className="flex flex-col space-y-4 p-1">
                      <div className="flex items-center justify-between space-x-2 rounded-lg border p-3 shadow-sm">
                          <div className="space-y-0.5">
                              <Label htmlFor="enable-logs" className="flex-grow">Включить логи отладки</Label>
                              <p className="text-xs text-muted-foreground">
                                  Включает консоль и подробные логи.
                              </p>
                          </div>
                          <Switch id="enable-logs" checked={gameSettings.enable_logs} onCheckedChange={checked => setGameSettings({...gameSettings, enable_logs: checked})}/>
                      </div>
                      <Button onClick={() => handleSaveSettings('game_settings', gameSettings)}>Сохранить настройки логов</Button>
                      <Button variant="outline" className="w-full" onClick={handleOpenLogsFolder}>
                          <Folder className="mr-2 h-4 w-4"/> Открыть папку логов
                      </Button>
                  </div>
              </TabsContent>

            </div>
          </ScrollArea>
        </Tabs>
      </DialogContent>
      <AddAccountDialog open={addAccountOpen} onOpenChange={setAddAccountOpen} onAccountAdded={handleAddAccount} />
    </Dialog>
  );
}
