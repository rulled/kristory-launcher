
'use client';

import { useState, useEffect, useCallback } from 'react';
import Image from 'next/image';
import { Button } from '@/components/ui/button';
import { SettingsDialog } from '@/components/settings-dialog';
import { Cog, Play, X, ChevronDown, Plus, Loader2, Download, RefreshCw, AlertCircle, FolderSearch } from 'lucide-react';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { cn } from '@/lib/utils';
import { AddAccountDialog } from '@/components/add-account-dialog';
import { useToast } from "@/hooks/use-toast";
import { Progress } from "@/components/ui/progress";

// Определяем типы для API
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
    };
  }
}

export type Account = {
  uuid: string;
  username: string;
  type: 'ely.by';
  accessToken: string;
  clientToken: string;
};

export type LauncherStatus = {
  is_processing: boolean;
  status_text: string;
  progress: number;
  version_info: {
      minecraft: string;
      fabric: string;
  };
  is_game_installed: boolean;
}

export type ServerStatus = {
  online: boolean;
  players_online?: number;
  players_max?: number;
}

export type GameSettings = {
  server_address: string;
  enable_logs: boolean;
  game_directory: string;
}

export type LauncherConfig = {
  accounts: Account[];
  last_selected_uuid: string | null;
  game_settings: GameSettings;
  // ... and other config fields
}

export const API_BASE_URL = 'http://127.0.0.1:5000';


export default function Home() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [selectedAccount, setSelectedAccount] = useState<Account | null>(null);
  const [isAddAccountOpen, setAddAccountOpen] = useState(false);
  const [isSettingsOpen, setSettingsOpen] = useState(false);
  const [launcherStatus, setLauncherStatus] = useState<LauncherStatus>({
    is_processing: false, status_text: "Подключение...", progress: 0,
    version_info: { minecraft: "N/A", fabric: "N/A" }, is_game_installed: false
  });
  const [serverStatus, setServerStatus] = useState<ServerStatus | null>(null);
  const [launcherConfig, setLauncherConfig] = useState<LauncherConfig | null>(null);
  const steveSkinUrl = `${API_BASE_URL}/api/skin/default-steve-placeholder`;
  const [skinUrl, setSkinUrl] = useState(steveSkinUrl);
  const [skinLoadError, setSkinLoadError] = useState(false);
  const { toast } = useToast();
  const [gameHasLaunched, setGameHasLaunched] = useState(false);
  const [updateMessage, setUpdateMessage] = useState('');
  const [isUpdateReady, setIsUpdateReady] = useState(false);
  const [isJavaErrorOpen, setJavaErrorOpen] = useState(false);
  const [javaErrorMessage, setJavaErrorMessage] = useState("Для запуска Minecraft требуется Java. Пожалуйста, установите рекомендованную версию и попробуйте снова.");


  // Listener for app updates
  useEffect(() => {
    if (window.electronAPI) {
      window.electronAPI.onUpdateMessage((message) => {
          setUpdateMessage(message);
      });
      window.electronAPI.onUpdateDownloaded(() => {
          setIsUpdateReady(true);
          setUpdateMessage('Обновление готово к установке!');
      });
    }

    return () => {
      if (window.electronAPI?.removeAllListeners) {
        window.electronAPI.removeAllListeners();
      }
    };
  }, []);

  const handleJavaError = (message: string) => {
    setJavaErrorMessage(message);
    setJavaErrorOpen(true);
  }

  const checkJavaVersion = useCallback(async () => {
    try {
        const res = await fetch(`${API_BASE_URL}/api/check-java`);
        if (!res.ok) {
            const errorData = await res.json();
            handleJavaError(errorData.error);
        }
    } catch (e) {
        console.error("Failed to check java version", e);
    }
  }, []);

  const fetchBackendData = useCallback(async (retries = 5, delay = 500) => {
    try {
      const configRes = await fetch(`${API_BASE_URL}/api/config`);
      if (!configRes.ok) throw new Error(`Backend not ready, status: ${configRes.status}`);

      const config: LauncherConfig = await configRes.json();
      
      // Basic validation to prevent setting a bad state
      if (!config || !Array.isArray(config.accounts)) {
          throw new Error("Invalid config received from backend");
      }

      const fetchedAccounts: Account[] = config.accounts || [];
      
      setLauncherConfig(config);
      setAccounts(fetchedAccounts);

      if (fetchedAccounts.length > 0) {
        const lastSelected = fetchedAccounts.find(acc => acc.uuid === config.last_selected_uuid);
        setSelectedAccount(lastSelected || fetchedAccounts[0]);
      } else {
        setSelectedAccount(null);
      }
      
      // After successfully fetching data, check java version
      checkJavaVersion();

    } catch (error) {
      console.error(`Attempt failed: ${error}`);
      if (retries > 0) {
        console.log(`Retrying in ${delay}ms... (${retries} retries left)`);
        setTimeout(() => fetchBackendData(retries - 1, delay * 2), delay);
      } else {
        console.error("Failed to fetch initial data after multiple retries:", error);
        setLauncherStatus(prev => ({ ...prev, status_text: "Ошибка API" }));
        setAccounts([]);
        setSelectedAccount(null);
      }
    }
  }, [checkJavaVersion]);
  
  const handleDataChange = useCallback(() => {
    fetchBackendData();
  }, [fetchBackendData]);

  // Fetch initial data on mount
  useEffect(() => {
    fetchBackendData();
  }, [fetchBackendData]);

  // Skin display logic
  useEffect(() => {
    setSkinLoadError(false);
    if (selectedAccount) {
      const customRenderUrl = `${API_BASE_URL}/api/skin/${selectedAccount.uuid}?t=${new Date().getTime()}`;
      setSkinUrl(customRenderUrl);
    } else {
      setSkinUrl(steveSkinUrl);
    }
  }, [selectedAccount, steveSkinUrl]);


  // Polling for statuses
  useEffect(() => {
    const pollStatus = async () => {
      try {
        const res = await fetch(`${API_BASE_URL}/api/status`);
        if (!res.ok) throw new Error("Connection lost");
        const data: LauncherStatus = await res.json();
        setLauncherStatus(data);
      } catch (error) {
        console.error("Poll status error:", error);
      }
    };
    const pollServerStatus = async () => {
        try {
            const res = await fetch(`${API_BASE_URL}/api/server-status`);
            if (!res.ok) throw new Error("Failed to fetch server status");
            const data: ServerStatus = await res.json();
            setServerStatus(data);
        } catch (error) {
            console.error("Poll server status error:", error);
            setServerStatus({ online: false });
        }
    };

    pollStatus();
    pollServerStatus();
    const statusIntervalId = setInterval(pollStatus, 2500);
    const serverIntervalId = setInterval(pollServerStatus, 20000); 

    return () => {
        clearInterval(statusIntervalId);
        clearInterval(serverIntervalId);
    };
  }, []);

  // Effect for handling specific errors from status updates
  useEffect(() => {
    const statusText = launcherStatus.status_text;
    
    // Проверяем только реальные ошибки, а не все сообщения содержащие "java"
    const isRealError = statusText.startsWith("Ошибка:") || 
                      statusText.startsWith("Error:") || 
                      statusText.includes("требуется Java") || // конкретные фразы ошибок
                      statusText.includes("не найдена") ||
                      statusText.includes("не удалось") ||
                      statusText.includes("Обнаружены изменения"); // for integrity check
    
    if (isRealError) {
      if (statusText.toLowerCase().includes("java")) {
        handleJavaError(statusText);
      } else {
        toast({
          title: "Произошла ошибка",
          description: statusText.replace("Ошибка: ", ""), // Убираем префикс
          variant: "destructive",
          duration: 8000
        });
      }
    }
  }, [launcherStatus.status_text, toast]);


  // Minimize window when game starts and re-enable button when it closes
  useEffect(() => {
    if (launcherStatus.status_text.startsWith("Игра запущена")) {
      if (window.electronAPI?.minimizeWindow) {
        window.electronAPI.minimizeWindow();
      }
      setGameHasLaunched(true);
    } else if (launcherStatus.status_text.includes("Игра закрыта") || launcherStatus.status_text.includes("Процесс остановлен")) {
      // When the process is finished, re-enable the play button
      setGameHasLaunched(false);
    }
  }, [launcherStatus.status_text]);


  const handleSelectAccount = async (account: Account) => {
    setSelectedAccount(account);
    try {
        await fetch(`${API_BASE_URL}/api/config`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ last_selected_uuid: account.uuid }),
        });
    } catch (error) {
        console.error("Failed to save selected account:", error);
    }
  }

  const handlePlayClick = async () => {
    if (launcherStatus.is_processing || !selectedAccount) {
        if (!selectedAccount) {
            toast({ title: "Ошибка", description: "Пожалуйста, выберите аккаунт.", variant: "destructive" });
        }
        return;
    }
    try {
      const response = await fetch(`${API_BASE_URL}/api/launch`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ selected_account_uuid: selectedAccount.uuid }),
      });
      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.message || 'Failed to start launch process');
      }
    } catch (error: any) {
      console.error("Launch error:", error);
      toast({ title: "Ошибка запуска", description: error.message, variant: "destructive" });
    }
  };

  const startVerificationProcess = async () => {
    if (launcherStatus.is_processing) return;
    try {
        const res = await fetch(`${API_BASE_URL}/api/verify-files`, { method: 'POST' });
        if (!res.ok) {
            const errorData = await res.json();
            throw new Error(errorData.error || 'Failed to start download process');
        }
        toast({ title: "Загрузка началась", description: "Вы можете следить за статусом в лаунчере." });
    } catch (error: any) {
        console.error("Download error:", error);
        toast({ title: "Ошибка загрузки", description: error.message, variant: "destructive" });
    }
  };

  const handleDownloadClick = async () => {
    if (!selectedAccount) {
        toast({ title: "Требуется аккаунт", description: "Пожалуйста, добавьте аккаунт, чтобы скачать сборку.", variant: "destructive"});
        return;
    }

    if (!window.electronAPI) return;

    const path = await window.electronAPI.selectDirectory({
        title: 'Выберите папку для установки KRISTORY',
    });

    if (path) {
        // Умное создание подпапки
        let finalPath = path.replace(/[\\/]+$/, ''); // Убираем слэш в конце
        if (!/kristory client/i.test(finalPath)) {
            finalPath = finalPath + (finalPath.includes('\\') ? '\\' : '/') + 'Kristory Client';
        }

        try {
            const saveRes = await fetch(`${API_BASE_URL}/api/config`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ game_settings: { game_directory: finalPath } })
            });
            if (!saveRes.ok) throw new Error("Не удалось сохранить путь к папке");

            await fetchBackendData();
            await startVerificationProcess();
        } catch (error: any) {
            toast({ title: "Ошибка", description: `Не удалось сохранить путь: ${error.message}`, variant: "destructive" });
        }
    } else {
        toast({ title: "Отменено", description: "Вы не выбрали папку для установки." });
    }
  };

  const isProcessing = launcherStatus.is_processing;
  const isGameDirSet = !!launcherConfig?.game_settings?.game_directory;

  const renderActionButton = () => {
    if (isProcessing) {
      return (
        <Loader2 className="h-12 w-12 animate-spin text-primary" />
      );
    }

    if (launcherStatus.is_game_installed) {
      return (
        <Button onClick={handlePlayClick} size="lg" disabled={!selectedAccount || gameHasLaunched}
          className="flex h-16 w-40 items-center justify-center overflow-hidden rounded-2xl bg-primary/80 text-xl font-bold text-primary-foreground shadow-lg backdrop-blur-sm transition-all duration-300 ease-in-out hover:bg-primary gap-4"
        >
          <Play className="h-6 w-6 fill-current" />
          <span className="whitespace-nowrap">Играть</span>
        </Button>
      );
    }

    // If not installed, always show Download/Setup button
    return (
      <Button onClick={isGameDirSet ? startVerificationProcess : handleDownloadClick} size="lg" disabled={!selectedAccount}
        className="flex h-16 w-56 items-center justify-center overflow-hidden rounded-2xl bg-primary/80 text-xl font-bold text-primary-foreground shadow-lg backdrop-blur-sm transition-all duration-300 ease-in-out hover:bg-primary gap-4"
      >
        {isGameDirSet ? <Download className="h-6 w-6" /> : <FolderSearch className="h-6 w-6" />}
        <span className="whitespace-nowrap">{isGameDirSet ? "Скачать" : "Выбрать папку"}</span>
      </Button>
    );
  };

  return (
    <>
      <main className="relative w-full h-screen flex flex-col items-center overflow-hidden border border-white/10 shadow-2xl">
        <Image
          src="background.jpg" alt="KRISTORY background" fill
          className="object-cover -z-10" unoptimized data-ai-hint="abstract texture"
        />
        <div className="absolute inset-0 bg-black/60 z-0" />
        <div className="relative z-10 w-full h-full flex flex-col">
          <div className={cn(
            "w-full h-14 bg-black/20 backdrop-blur-lg flex items-center justify-between px-4 border-b border-white/10 flex-shrink-0",
            "draggable-region"
          )}>
            <Image src="logo.png" alt="KRISTORY Logo" width={120} height={26} unoptimized />
            <Button
              variant="ghost" size="icon"
              className="text-white/70 hover:text-white hover:bg-white/10 h-8 w-8 non-draggable-region"
              onClick={() => window.close()}
            >
              <X className="h-5 w-5" />
              <span className="sr-only">Закрыть</span>
            </Button>
          </div>
          
          <div className="flex-1 w-full flex flex-col items-center justify-between py-6 px-4">
            
            {accounts.length === 0 ? (
                <Button variant="outline" onClick={() => setAddAccountOpen(true)}
                  className="flex items-center justify-center gap-2 w-72 h-14 cursor-pointer rounded-xl border-white/20 bg-black/40 px-4 text-lg text-white backdrop-blur-md hover:bg-black/50 transition-colors"
                >
                  <Plus className="h-5 w-5" />
                  <span>Добавить аккаунт</span>
                </Button>
              ) : (
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button variant="outline"
                      className="flex items-center justify-between gap-2 w-72 h-14 cursor-pointer rounded-xl border-white/20 bg-black/40 px-4 text-lg text-white backdrop-blur-md hover:bg-black/50 transition-colors"
                    >
                      <span>{selectedAccount ? selectedAccount.username : 'Выберите аккаунт'}</span>
                      <ChevronDown className="h-5 w-5 opacity-70" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end" className="w-72 bg-black/60 backdrop-blur-xl border-white/20 text-white">
                    {accounts.map((acc) => (
                      <DropdownMenuItem key={acc.uuid} onSelect={() => handleSelectAccount(acc)} className="cursor-pointer focus:bg-white/20">
                        {acc.username}
                      </DropdownMenuItem>
                    ))}
                    <DropdownMenuSeparator className="bg-white/10" />
                    <DropdownMenuItem onSelect={() => setAddAccountOpen(true)} className="cursor-pointer focus:bg-white/20">
                      <Plus className="mr-2 h-4 w-4" />
                      <span>Добавить еще</span>
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
            )}

            <div className="bg-black/30 p-2 rounded-lg backdrop-blur-sm border border-white/10 shadow-lg w-[100px] h-[200px] flex items-center justify-center">
              <Image
                key={skinUrl} src={skinLoadError ? steveSkinUrl : skinUrl}
                onError={() => { if (!skinLoadError) setSkinLoadError(true); }}
                alt="Minecraft player skin" width={80} height={160}
                className="pixelated" data-ai-hint="minecraft skin" unoptimized
              />
            </div>

            <div className="flex flex-col items-center justify-start gap-2 w-full">
              <div className="relative flex h-20 w-56 items-center justify-center">
                 {renderActionButton()}
              </div>

              <div className="h-10 w-full max-w-xs flex flex-col items-center justify-center gap-2">
                  {isProcessing ? (
                      <>
                          <p className="text-center text-sm text-white/80 opacity-80 truncate">{launcherStatus.status_text}</p>
                          <Progress value={launcherStatus.progress} className="w-full h-2" />
                      </>
                  ) : (
                    <div className={cn("text-center text-sm text-white/80 opacity-80 flex items-center gap-2", launcherStatus.status_text.includes("Ошибка:") && "text-destructive")}>
                        {launcherStatus.status_text.includes("Ошибка:") && <AlertCircle className="h-4 w-4" />}
                        <span>
                            {launcherStatus.status_text.includes("Ошибка:") 
                                ? launcherStatus.status_text.replace("Ошибка: ", "")
                                : (launcherStatus.is_game_installed ? "Готов к запуску" : "Готов к установке")
                            }
                        </span>
                    </div>
                  )}
              </div>

              <div className="w-full flex justify-center">
                {!serverStatus ? (
                    <div className="flex items-center gap-2 text-sm text-white/70 bg-black/30 backdrop-blur-md px-4 py-2 rounded-full border border-white/10">
                        <Loader2 className="h-4 w-4 animate-spin" />
                        <span>Статус сервера...</span>
                    </div>
                ) : (
                    <div className="flex items-center gap-2.5 text-sm text-white/90 bg-black/30 backdrop-blur-md px-4 py-2 rounded-full border border-white/10">
                        <div className={cn("h-2.5 w-2.5 rounded-full transition-colors", serverStatus.online ? 'bg-green-400 shadow-[0_0_8px_0px_#22c55e]' : 'bg-red-500')} />
                        <span className="font-medium">{serverStatus.online ? 'Сервер онлайн' : 'Сервер оффлайн'}</span>
                        {serverStatus.online && typeof serverStatus.players_online !== 'undefined' && (
                            <>
                                <span className="text-white/40">|</span>
                                <span>{serverStatus.players_online} игроков</span>
                            </>
                        )}
                    </div>
                )}
              </div>
            </div>
          </div>

          <div className="w-full h-16 bg-black/20 backdrop-blur-lg flex items-center justify-between px-4 border-t border-white/10 flex-shrink-0">
            <div className="text-sm text-white/70 min-w-0 pr-2">
                {isUpdateReady ? (
                    <Button variant="ghost" onClick={() => window.electronAPI.restartApp()} className="text-primary hover:text-primary hover:bg-white/10 animate-pulse">
                        <RefreshCw className="mr-2 h-4 w-4"/>
                        Перезапустить для обновления
                    </Button>
                ) : (
                    <span className="truncate">{updateMessage}</span>
                )}
            </div>
            <SettingsDialog open={isSettingsOpen} onOpenChange={setSettingsOpen} onSettingsChange={handleDataChange} launcherStatus={launcherStatus}>
              <Button variant="ghost" size="icon" className="text-white/70 hover:text-white hover:bg-white/10 group flex-shrink-0">
                <Cog className="h-6 w-6 transition-transform duration-1000 group-hover:rotate-180" />
                <span className="sr-only">Настройки</span>
              </Button>
            </SettingsDialog>
          </div>
        </div>
      </main>
      <AddAccountDialog open={isAddAccountOpen} onOpenChange={setAddAccountOpen} onAccountAdded={handleDataChange}/>
      <AlertDialog open={isJavaErrorOpen} onOpenChange={setJavaErrorOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle className="flex items-center gap-2">
              <AlertCircle className="text-destructive" />
              Проблема со средой Java
            </AlertDialogTitle>
            <AlertDialogDescription>
              {javaErrorMessage.replace("Ошибка: ", "")}
              <br/><br/>
              После установки вы можете указать путь к файлу <code className="bg-muted px-1 py-0.5 rounded">javaw.exe</code> в настройках, если лаунчер не найдет его автоматически.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
             <Button variant="outline" onClick={() => setJavaErrorOpen(false)}>
                Понятно
            </Button>
            <div style={{ height: 20 }} />
            <AlertDialogAction asChild>
              <a href="https://www.azul.com/core-post-download/?endpoint=zulu&uuid=5386cd76-d4d1-4687-992f-461db0ff9959" target="_blank" rel="noopener noreferrer">
                Скачать Zulu JDK 21 (x64)
              </a>
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
