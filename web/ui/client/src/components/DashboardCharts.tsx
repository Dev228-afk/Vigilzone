import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from "recharts";

interface DashboardChartsProps {
  data: Array<{ name: string; value: number; color: string }>;
}

export default function DashboardCharts({ data }: DashboardChartsProps) {
  if (!data || data.length === 0) return null;

  return (
    <ResponsiveContainer width="100%" height={250}>
      <PieChart>
        <Pie
          data={data}
          dataKey="value"
          nameKey="name"
          innerRadius={55}
          outerRadius={85}
          paddingAngle={3}
        >
          {data.map((entry, index) => (
            <Cell
              key={`${entry.name}-${index}`}
              fill={entry.color}
              stroke="hsl(var(--background))"
              strokeWidth={2}
            />
          ))}
        </Pie>
        <Tooltip
          content={({ active, payload }) => {
            if (active && payload && payload.length) {
              return (
                <div className="rounded-xl border border-border bg-popover p-3 text-sm text-popover-foreground shadow-lg">
                  <p className="font-medium">{payload[0].name}</p>
                  <p className="text-primary">{payload[0].value}</p>
                </div>
              );
            }
            return null;
          }}
        />
      </PieChart>
    </ResponsiveContainer>
  );
}
