import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { Avatar, Badge, Card, Spinner } from "../components/ui";
import { useAuth } from "../state/auth";

interface Person {
  id: string;
  name: string;
  email: string;
  avatar_color: string;
  job_title: string | null;
  role: string;
  meeting_count: number;
  open_task_count: number;
}

export default function People() {
  const { activeOrg } = useAuth();
  const { data: people, isLoading } = useQuery({
    queryKey: ["people", activeOrg?.id],
    queryFn: () => api<Person[]>("/api/people"),
    enabled: !!activeOrg,
  });

  return (
    <div className="mx-auto max-w-4xl px-6 py-10">
      <h1 className="mb-6 text-2xl font-semibold tracking-tight text-ink-900">Personas</h1>
      {isLoading && <div className="flex justify-center py-16 text-ink-300"><Spinner className="h-6 w-6" /></div>}
      <div className="grid gap-4 sm:grid-cols-2">
        {people?.map((person) => (
          <Link key={person.id} to={`/people/${person.id}`}>
            <Card className="flex items-center gap-4 transition-shadow hover:shadow-md">
              <Avatar name={person.name} color={person.avatar_color} size={44} />
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium text-ink-900">{person.name}</p>
                <p className="truncate text-xs text-ink-400">{person.job_title ?? person.email}</p>
                <p className="mt-1 text-xs text-ink-500">
                  {person.meeting_count} reuniones · {person.open_task_count} tareas abiertas
                </p>
              </div>
              <Badge tone={person.role === "owner" ? "indigo" : "gray"}>{person.role}</Badge>
            </Card>
          </Link>
        ))}
      </div>
    </div>
  );
}
