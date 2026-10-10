import { Router, type IRouter } from "express";
import healthRouter from "./health";
import elevenLabsRouter from "./elevenlabs";

const router: IRouter = Router();

router.use(healthRouter);
router.use(elevenLabsRouter);

export default router;
