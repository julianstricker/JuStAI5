import { createContext, useContext } from "react";

import type { Me } from "@/shared/types";

export const AuthContext = createContext<Me | null>(null);

export function useMe(): Me {
  const me = useContext(AuthContext);
  if (!me) throw new Error("not authenticated");
  return me;
}

export function useIsAdmin(): boolean {
  return useMe().role === "admin";
}
