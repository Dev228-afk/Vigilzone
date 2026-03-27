import { Flame, UserX, AlertTriangle, Car, HelpCircle } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

interface AlertCardProps {
  type: "fire" | "intrusion" | "violence" | "crash" | "robbery" | "stranger" | "other" | string;
  location: string;
  time: string;
  entity?: string;
  confidence?: number;
  sourceLabel?: string;
  onClick?: () => void;
}

const alertConfig: Record<string, { icon: React.ComponentType<{ className?: string }>; label: string; color: string }> = {
  fire: {
    icon: Flame,
    label: "Fire",
    color: "text-destructive",
  },
  intrusion: {
    icon: UserX,
    label: "Intrusion",
    color: "text-orange-600",
  },
  violence: {
    icon: AlertTriangle,
    label: "Violence",
    color: "text-orange-600",
  },
  crash: {
    icon: Car,
    label: "Crash",
    color: "text-orange-600",
  },
  robbery: {
    icon: AlertTriangle,
    label: "Robbery",
    color: "text-orange-600",
  },
  stranger: {
    icon: UserX,
    label: "Stranger",
    color: "text-orange-600",
  },
  other: {
    icon: HelpCircle,
    label: "Alert",
    color: "text-muted-foreground",
  },
};

const defaultConfig = {
  icon: HelpCircle,
  label: "Alert",
  color: "text-muted-foreground",
};

export default function AlertCard({ type, location, time, entity, confidence, sourceLabel, onClick }: AlertCardProps) {
  const config = alertConfig[type] ?? defaultConfig;
  const Icon = config.icon;

  return (
    <Card 
      className={`p-4 cursor-pointer hover-elevate ${onClick ? 'active-elevate-2' : ''}`}
      onClick={onClick}
      data-testid={`card-alert-${type}`}
    >
      <div className="flex items-start gap-3">
        <div className={`${config.color} mt-1`}>
          <Icon className="w-5 h-5" />
        </div>
        <div className="flex-1 min-w-0">
          <h4 className="font-semibold text-sm">{config.label} detected</h4>
          <p className="text-sm text-muted-foreground mt-1">
            {location} — {time}
            {confidence && ` — Confidence ${confidence}%`}
          </p>
          {sourceLabel && (
            <div className="mt-1.5">
              <Badge variant={sourceLabel.toLowerCase() === "webcam" ? "secondary" : "outline"} className="text-[10px] px-1.5 py-0">
                {sourceLabel}
              </Badge>
            </div>
          )}
          {entity && (
            <p className="text-sm mt-1">
              <span className="text-muted-foreground">Entity:</span>{" "}
              <span className={entity.includes("Unknown") ? "text-orange-600 font-medium" : ""}>{entity}</span>
            </p>
          )}
        </div>
      </div>
    </Card>
  );
}
