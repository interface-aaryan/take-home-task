'use client';

import { useState, useEffect } from 'react';
import { RevisionStatus, RevisionStatusUpdate, RevisionStatusStore } from '../utils/types';

// Using localStorage to simulate a backend for simplicity
// In a real application, we would use a database and WebSockets/Server-Sent Events

const STORAGE_KEY = 'revision_status_store';

export function useRevisionStatus(orgId: string | null, userId: string | null) {
  const [revisionStatus, setRevisionStatus] = useState<RevisionStatus | null>(null);
  
  // Initialize or get revision status for the org
  useEffect(() => {
    if (!orgId) return;
    
    // Load the entire store from localStorage
    const loadStore = (): RevisionStatusStore => {
      if (typeof window === 'undefined') return {};
      
      const stored = localStorage.getItem(STORAGE_KEY);
      return stored ? JSON.parse(stored) : {};
    };
    
    const store = loadStore();
    
    // If this org doesn't have a status yet, create one
    if (!store[orgId]) {
      store[orgId] = {
        orgId,
        currentStatus: 0,
        updates: []
      };
      localStorage.setItem(STORAGE_KEY, JSON.stringify(store));
    }
    
    setRevisionStatus(store[orgId]);
    
    // Set up event listener for storage events (when other tabs update)
    const handleStorageChange = (event: StorageEvent) => {
      if (event.key === STORAGE_KEY && event.newValue) {
        const newStore: RevisionStatusStore = JSON.parse(event.newValue);
        if (newStore[orgId]) {
          setRevisionStatus(newStore[orgId]);
        }
      }
    };
    
    window.addEventListener('storage', handleStorageChange);
    
    return () => {
      window.removeEventListener('storage', handleStorageChange);
    };
  }, [orgId]);
  
  // Function to update the revision status
  const updateStatus = (newStatus: number, comment?: string) => {
    if (!orgId || !userId) return;
    
    // Small artificial delay to simulate network request
    // In a real application, this would be an API call
    return new Promise<void>((resolve) => {
      setTimeout(() => {
        try {
          const store = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');
          
          // Create a new update
          const update: RevisionStatusUpdate = {
            userId,
            timestamp: new Date().toISOString(),
            status: newStatus,
            comment
          };
          
          // Update the store
          const updatedStatus: RevisionStatus = {
            orgId,
            currentStatus: newStatus,
            updates: [...(store[orgId]?.updates || []), update]
          };
          
          store[orgId] = updatedStatus;
          
          // Save to localStorage
          localStorage.setItem(STORAGE_KEY, JSON.stringify(store));
          
          // Update local state
          setRevisionStatus(updatedStatus);
          
          // Notify other tabs/windows by dispatching an event
          window.dispatchEvent(new StorageEvent('storage', {
            key: STORAGE_KEY,
            newValue: JSON.stringify(store)
          }));
          
          resolve();
        } catch (error) {
          console.error('Error updating status:', error);
          throw error;
        }
      }, 400); // Simulate network delay
    });
  };
  
  return {
    revisionStatus,
    updateStatus
  };
}