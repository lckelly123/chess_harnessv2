import { createContext } from "react";

export const ModelExchangeContext = createContext<((runId: string, passNumber: number) => Promise<void>) | null>(null);
