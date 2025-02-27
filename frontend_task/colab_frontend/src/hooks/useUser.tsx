'use client';

import { useState, useEffect } from 'react';
import { getCookie, setCookie } from '../utils/cookies';

interface UserContextState {
  userId: string | null;
  orgId: string | null;
  isLoading: boolean;
  setUserId: (id: string) => void;
  setOrgId: (id: string) => void;
}

export function useUser(): UserContextState {
  const [userId, setUserIdState] = useState<string | null>(null);
  const [orgId, setOrgIdState] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  // Load user & org IDs from cookies on mount
  useEffect(() => {
    const userIdFromCookie = getCookie('userId');
    const orgIdFromCookie = getCookie('orgId');
    
    setUserIdState(userIdFromCookie);
    setOrgIdState(orgIdFromCookie);
    setIsLoading(false);
  }, []);

  const setUserId = (id: string) => {
    setCookie('userId', id);
    setUserIdState(id);
  };

  const setOrgId = (id: string) => {
    setCookie('orgId', id);
    setOrgIdState(id);
  };

  return {
    userId,
    orgId,
    isLoading,
    setUserId,
    setOrgId
  };
}