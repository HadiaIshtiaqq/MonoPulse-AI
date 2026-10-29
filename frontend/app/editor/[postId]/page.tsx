"use client";

import { Suspense, useEffect, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import Link from "next/link";
import { Loader2 } from "lucide-react";
import { api, type Campaign, type SocialPost } from "@/lib/api";
import { Editor } from "@/components/editor/Editor";

/** The full-screen design editor for one post: /editor/<post id>?c=<campaign id>. */
export default function EditorPage() {
  return <Suspense fallback={null}><EditorRoute /></Suspense>;
}

function EditorRoute() {
  const { postId } = useParams<{ postId: string }>();
  const campaignId = useSearchParams().get("c") || "";
  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!campaignId) { setError("Open the editor from a post."); return; }
    api.campaign(campaignId).then(setCampaign).catch((e) => setError((e as Error).message));
  }, [campaignId]);

  const post = campaign?.posts.find((p) => p.id === postId);
  if (error || (campaign && !post)) {
    return (
      <div className="grid min-h-[60vh] place-items-center text-center">
        <div>
          <p className="font-semibold">{error || "That post isn't in this campaign."}</p>
          <Link href={campaignId ? `/campaign/${campaignId}` : "/campaigns"} className="btn-ghost btn-sm mt-3">Back</Link>
        </div>
      </div>
    );
  }
  if (!campaign || !post) return <div className="grid min-h-[60vh] place-items-center"><Loader2 className="animate-spin text-slate-400" /></div>;
  return (
    <Editor key={post.id} post={post} brand={campaign.brand} campaignId={campaign.id}
      onSaved={(p: SocialPost) => setCampaign((c) => (c ? { ...c, posts: c.posts.map((x) => (x.id === p.id ? p : x)) } : c))} />
  );
}
