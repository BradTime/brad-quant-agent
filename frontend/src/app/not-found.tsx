import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';

export default function NotFound() {
  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle className="text-4xl">404</CardTitle>
          <CardDescription>页面未找到</CardDescription>
        </CardHeader>
        <CardContent>
          <p className="text-muted-foreground">
            抱歉，您访问的页面不存在。请检查 URL 是否正确，或返回首页。
          </p>
        </CardContent>
        <CardFooter>
          <Link href="/">
            <Button>返回首页</Button>
          </Link>
        </CardFooter>
      </Card>
    </div>
  );
}

