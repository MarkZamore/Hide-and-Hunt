package lanminecraft.hideandhunt;

import java.io.IOException;
import java.nio.file.Files;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HexFormat;
import java.util.List;
import java.util.Set;
import net.fabricmc.loader.api.FabricLoader;
import org.objectweb.asm.Opcodes;
import org.objectweb.asm.tree.AbstractInsnNode;
import org.objectweb.asm.tree.ClassNode;
import org.objectweb.asm.tree.FieldInsnNode;
import org.objectweb.asm.tree.IincInsnNode;
import org.objectweb.asm.tree.InsnNode;
import org.objectweb.asm.tree.IntInsnNode;
import org.objectweb.asm.tree.JumpInsnNode;
import org.objectweb.asm.tree.LdcInsnNode;
import org.objectweb.asm.tree.MethodInsnNode;
import org.objectweb.asm.tree.MethodNode;
import org.objectweb.asm.tree.VarInsnNode;
import org.spongepowered.asm.mixin.extensibility.IMixinConfigPlugin;
import org.spongepowered.asm.mixin.extensibility.IMixinInfo;

public final class BridgePlugin implements IMixinConfigPlugin {
    static final String HOSTING = "de/hideandhunt/client/host/Hosting";
    static final String PENDING = HOSTING + "$Pending";
    static final String CREATE = "de/hideandhunt/client/screen/CreateWorldView";
    static final String MENU = "de/hideandhunt/client/screen/HhMenuView";
    static final String PUBLISH = "(Lnet/minecraft/server/MinecraftServer$MultiplayerScope;ZI)Z";
    static final String SERVER = "net/minecraft/client/server/IntegratedServer";
    private static final String UPNP = "de/hideandhunt/client/host/Upnp";
    private static final String WIDGETS = "de/hideandhunt/client/ui/Widgets";
    private static final String DRAW = "(Lde/hideandhunt/client/ui/Canvas;IIF)V";
    private static final String TOGGLE = "(Lde/hideandhunt/client/ui/Canvas;IIZIIF)V";
    private static final String TEXT = "(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;[Ljava/lang/Object;)Lnet/minecraft/network/chat/MutableComponent;";

    @Override
    public void onLoad(String mixinPackage) {
        verifyOrigin("hideandhunt", HOSTING, "e04e557bbaf303b416e6e174b32d128dc53cdd29d3786add530f39bf27af1963");
        verifyOrigin("hideandhunt", PENDING, "473ea2e9bb882aaf2a37e1f04f9439533d5a592ded6c6acbdf7cc8a2f1b403af");
        verifyOrigin("hideandhunt", CREATE, "4652c5ff1a0a53280cee61bcc2aaa2e766f010bec769d07f4eedc65055b82fa3");
        verifyOrigin("hideandhunt", MENU, "e1b138a43962f4c54ea44af99b8525f0e9916569e20aca3e205bfa228a4e8dec");
    }

    private static void verifyOrigin(String mod, String className, String expected) {
        var container = FabricLoader.getInstance().getModContainer(mod)
            .orElseThrow(() -> incompatible("missing " + mod));
        var path = container.findPath(className + ".class")
            .orElseThrow(() -> incompatible("missing " + className));
        try {
            byte[] hash = MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(path));
            if (!HexFormat.of().formatHex(hash).equals(expected)) {
                throw incompatible("unexpected bytes for " + className);
            }
        } catch (IOException | NoSuchAlgorithmException failure) {
            throw new IllegalStateException("Cannot check Hide and Hunt bridge class " + className, failure);
        }
    }

    @Override
    public void postApply(String targetClassName, ClassNode target, String mixinClassName, IMixinInfo mixinInfo) {
        apply(target);
    }

    static void apply(ClassNode target) {
        switch (target.name) {
            case HOSTING -> patchHosting(target);
            case CREATE -> patchCreate(target);
            case MENU -> patchMenu(target);
            default -> throw incompatible("unexpected target " + target.name);
        }
    }

    private static void patchHosting(ClassNode target) {
        MethodNode joined = method(target, "joined", "()V");
        call(joined, Opcodes.INVOKEVIRTUAL, SERVER, "publishServer", PUBLISH);
        MethodInsnNode message = replaceText(joined, "hh.host.open", "world.open",
            "Deine Welt ist offen. Steam-Freunde finden sie im Mehrspielermenü.",
            "Your world is open. Steam friends can find it in Multiplayer.");
        AbstractInsnNode chat = next(message);
        AbstractInsnNode tail = next(chat);
        if (!isCall(chat, Opcodes.INVOKESTATIC, HOSTING, "chat", "(Lnet/minecraft/network/chat/Component;)V")
            || tail.getOpcode() != Opcodes.ALOAD
            || !isCall(next(tail), Opcodes.INVOKEVIRTUAL, PENDING, "upnp", "()Z")) {
            throw incompatible("unknown code after native publication");
        }
        // Keep native port retries, the failure branch and the success message.
        // An old world's saved upnp flag is no longer consulted here.
        removeCode(joined, tail, null);
        joined.instructions.add(new InsnNode(Opcodes.RETURN));

        MethodNode mapping = method(target, "lambda$joined$1", "(ILnet/minecraft/client/Minecraft;)V");
        call(mapping, Opcodes.INVOKESTATIC, UPNP, "open", "(I)L" + UPNP + "$Mapping;");
        target.methods.remove(mapping);
        target.methods.remove(method(target, "lambda$joined$2", "(L" + UPNP + "$Mapping;I)V"));
    }

    private static void patchCreate(ClassNode target) {
        MethodNode draw = method(target, "draw", DRAW);
        MethodInsnNode toggle = call(draw, Opcodes.INVOKEVIRTUAL, CREATE, "toggle", TOGGLE);
        MethodInsnNode relay = call(draw, Opcodes.INVOKESTATIC, HOSTING, "relayMod", "()Z");
        List<MethodInsnNode> loops = calls(draw, Opcodes.INVOKEINTERFACE, "java/util/Iterator", "hasNext", "()Z");
        if (loops.size() != 2
            || !(next(loops.getFirst()) instanceof JumpInsnNode portHintEnd) || portHintEnd.getOpcode() != Opcodes.IFEQ
            || !(next(portHintEnd.label) instanceof IincInsnNode spacer) || spacer.var != 11 || spacer.incr != 34
            || !(next(loops.getLast()) instanceof JumpInsnNode relayHintEnd) || relayHintEnd.getOpcode() != Opcodes.IFEQ
            || draw.instructions.indexOf(spacer) >= draw.instructions.indexOf(toggle)
            || draw.instructions.indexOf(toggle) >= draw.instructions.indexOf(relay)
            || draw.instructions.indexOf(relay) >= draw.instructions.indexOf(relayHintEnd)) {
            throw incompatible("unknown world creation toggle layout");
        }
        removeCode(draw, spacer, next(relayHintEnd.label));
        target.methods.remove(method(target, "toggle", TOGGLE));
        List<IntInsnNode> heights = Arrays.stream(draw.instructions.toArray())
            .filter(node -> node instanceof IntInsnNode value && value.getOpcode() == Opcodes.SIPUSH
                && value.operand == 196)
            .map(IntInsnNode.class::cast).toList();
        if (heights.size() != 1) {
            throw incompatible("unknown world creation form height");
        }
        heights.getFirst().operand = 170;

        MethodNode click = method(target, "click", "(DDII)Z");
        MethodInsnNode inside = call(click, Opcodes.INVOKESTATIC, CREATE, "inside", "(DDIIII)Z");
        MethodInsnNode widgetClick = call(click, Opcodes.INVOKEVIRTUAL, WIDGETS, "click", "(DD)Ljava/lang/String;");
        if (!(next(inside) instanceof JumpInsnNode continueClick) || continueClick.getOpcode() != Opcodes.IFEQ
            || next(continueClick.label).getOpcode() != Opcodes.ALOAD
            || click.instructions.indexOf(continueClick.label) >= click.instructions.indexOf(widgetClick)) {
            throw incompatible("unknown world creation toggle hit area");
        }
        removeCode(click, click.instructions.getFirst(), next(continueClick.label));

        MethodNode create = method(target, "create", "()V");
        MethodInsnNode minecraft = call(create, Opcodes.INVOKESTATIC, "net/minecraft/client/Minecraft",
            "getInstance", "()Lnet/minecraft/client/Minecraft;");
        AbstractInsnNode flag = previous(minecraft);
        AbstractInsnNode receiver = previous(flag);
        if (!(flag instanceof FieldInsnNode field) || flag.getOpcode() != Opcodes.GETFIELD
            || !field.owner.equals(CREATE) || !field.name.equals("upnp") || !field.desc.equals("Z")
            || !(receiver instanceof VarInsnNode local) || local.getOpcode() != Opcodes.ALOAD || local.var != 0) {
            throw incompatible("unknown world creation internet flag");
        }
        create.instructions.remove(receiver);
        create.instructions.set(flag, new InsnNode(Opcodes.ICONST_0));
    }

    private static void patchMenu(ClassNode target) {
        MethodNode init = method(target, "init", "()V");
        MethodInsnNode refresh = call(init, Opcodes.INVOKEVIRTUAL, MENU, "refresh", "()V");
        call(init, Opcodes.INVOKEVIRTUAL,
            "net/minecraft/client/server/LanServerDetection$LanServerDetector", "start", "()V");
        if (!(previous(refresh) instanceof VarInsnNode receiver)
            || receiver.getOpcode() != Opcodes.ALOAD || receiver.var != 0) {
            throw incompatible("unknown menu refresh");
        }
        // Keep local worlds and manual addresses. The automatic list belongs to
        // Minecraft's Multiplayer screen and the shared Steam discovery adapter.
        init.instructions.clear();
        init.tryCatchBlocks.clear();
        init.localVariables = null;
        init.instructions.add(new VarInsnNode(Opcodes.ALOAD, 0));
        init.instructions.add(new MethodInsnNode(refresh.getOpcode(), refresh.owner, refresh.name, refresh.desc, false));
        init.instructions.add(new InsnNode(Opcodes.RETURN));
        init.maxStack = 1;
        init.maxLocals = 1;

        MethodNode draw = method(target, "draw", DRAW);
        replaceText(draw, "hh.mm.internet", "world.steam", "Steam", "Steam");
        replaceText(draw, "hh.mm.lan", "world.steam", "Steam", "Steam");
        replaceText(draw, "hh.mm.join.sub", "saved.title", "gespeicherte Adressen", "saved addresses");
        replaceText(draw, "hh.mm.join.none", "saved.empty", "Keine gespeicherten Adressen.", "No saved addresses.");
        replaceText(draw, "hh.mm.join.none2", "saved.hint",
            "Steam-Welten stehen im Mehrspielermenü.", "Find Steam worlds in Multiplayer.");
    }

    private static void removeCode(MethodNode method, AbstractInsnNode start, AbstractInsnNode end) {
        for (AbstractInsnNode instruction = start; instruction != end;) {
            AbstractInsnNode following = instruction.getNext();
            method.instructions.remove(instruction);
            instruction = following;
        }
        // The original debug scopes can point to labels in the removed block.
        method.localVariables = null;
    }

    private static MethodInsnNode replaceText(MethodNode method, String key, String suffix, String german, String english) {
        List<LdcInsnNode> keys = new ArrayList<>();
        for (AbstractInsnNode instruction : method.instructions) {
            if (instruction instanceof LdcInsnNode constant && key.equals(constant.cst)) {
                keys.add(constant);
            }
        }
        if (keys.size() != 1) {
            throw incompatible("expected one text key " + key);
        }
        LdcInsnNode sourceKey = keys.getFirst();
        AbstractInsnNode germanSource = next(sourceKey);
        AbstractInsnNode englishSource = next(germanSource);
        AbstractInsnNode count = next(englishSource);
        AbstractInsnNode array = next(count);
        if (!(germanSource instanceof LdcInsnNode de) || !(de.cst instanceof String)
            || !(englishSource instanceof LdcInsnNode en) || !(en.cst instanceof String)
            || count.getOpcode() != Opcodes.ICONST_0 || array.getOpcode() != Opcodes.ANEWARRAY
            || !isCall(next(array), Opcodes.INVOKESTATIC, "de/hideandhunt/T", "c", TEXT)) {
            throw incompatible("unknown text call for " + key);
        }
        sourceKey.cst = "lanminecraft.hideandhunt." + suffix;
        de.cst = german;
        en.cst = english;
        return (MethodInsnNode) next(array);
    }

    private static MethodNode method(ClassNode target, String name, String descriptor) {
        return target.methods.stream()
            .filter(method -> method.name.equals(name) && method.desc.equals(descriptor))
            .findFirst().orElseThrow(() -> incompatible(target.name + "." + name + descriptor));
    }

    private static MethodInsnNode call(MethodNode method, int opcode, String owner, String name, String descriptor) {
        List<MethodInsnNode> matches = calls(method, opcode, owner, name, descriptor);
        if (matches.size() != 1) {
            throw incompatible("expected one call to " + owner + "." + name + " in " + method.name);
        }
        return matches.getFirst();
    }

    private static List<MethodInsnNode> calls(MethodNode method, int opcode, String owner, String name, String descriptor) {
        List<MethodInsnNode> matches = new ArrayList<>();
        for (AbstractInsnNode instruction : method.instructions) {
            if (isCall(instruction, opcode, owner, name, descriptor)) {
                matches.add((MethodInsnNode) instruction);
            }
        }
        return matches;
    }

    private static boolean isCall(AbstractInsnNode instruction, int opcode, String owner, String name, String descriptor) {
        return instruction instanceof MethodInsnNode call && call.getOpcode() == opcode
            && call.owner.equals(owner) && call.name.equals(name) && call.desc.equals(descriptor);
    }

    private static AbstractInsnNode previous(AbstractInsnNode instruction) {
        do {
            instruction = instruction.getPrevious();
        } while (instruction != null && instruction.getOpcode() < 0);
        if (instruction == null) {
            throw incompatible("missing previous bytecode instruction");
        }
        return instruction;
    }

    private static AbstractInsnNode next(AbstractInsnNode instruction) {
        do {
            instruction = instruction.getNext();
        } while (instruction != null && instruction.getOpcode() < 0);
        if (instruction == null) {
            throw incompatible("missing next bytecode instruction");
        }
        return instruction;
    }

    private static IllegalStateException incompatible(String reason) {
        return new IllegalStateException("Hide and Hunt bridge requires its pinned upstream profile: " + reason);
    }

    @Override
    public String getRefMapperConfig() {
        return null;
    }

    @Override
    public boolean shouldApplyMixin(String targetClassName, String mixinClassName) {
        return true;
    }

    @Override
    public void acceptTargets(Set<String> myTargets, Set<String> otherTargets) {
    }

    @Override
    public List<String> getMixins() {
        return null;
    }

    @Override
    public void preApply(String targetClassName, ClassNode targetClass, String mixinClassName, IMixinInfo mixinInfo) {
    }
}
