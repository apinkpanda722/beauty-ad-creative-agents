"use client";
import { createContext } from "react";

export const OpenGraphPathContext = createContext<((ids: string[]) => void) | null>(null);
