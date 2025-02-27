// Type definitions for the application

export interface RevisionStatusUpdate {
  userId: string;
  timestamp: string;
  status: number; // Rating between 0 and 9
  comment?: string;
}

export interface RevisionStatus {
  orgId: string;
  currentStatus: number;
  updates: RevisionStatusUpdate[];
}

export interface RevisionStatusStore {
  [orgId: string]: RevisionStatus;
}