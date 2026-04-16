import { Loader2 } from "lucide-react";

export default function LoadingDisplay() {
  return (
    <div className="flex h-[80vh] w-full flex-col items-center justify-center gap-3">
      <Loader2 className="h-10 w-10 animate-spin text-primary" />
      <p className="text-sm font-medium text-muted-foreground animate-pulse">
        Loading VigilZone...
      </p>
    </div>
  );
}
