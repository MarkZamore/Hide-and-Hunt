package lanminecraft.hideandhunt;

import java.nio.file.Path;
import java.util.zip.ZipFile;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.Opcodes;
import org.objectweb.asm.tree.ClassNode;
import org.objectweb.asm.tree.LdcInsnNode;
import org.objectweb.asm.tree.MethodInsnNode;
import org.objectweb.asm.tree.MethodNode;
import org.objectweb.asm.tree.analysis.Analyzer;
import org.objectweb.asm.tree.analysis.BasicVerifier;

public final class ExactTargets {
    private ExactTargets() {
    }

    public static void main(String[] args) throws Exception {
        try (ZipFile author = new ZipFile(Path.of(args[0]).toFile())) {
            verifyHosting(read(author, BridgePlugin.HOSTING));
            verifyMenu(read(author, BridgePlugin.MENU));
            verifyCreate(read(author, BridgePlugin.CREATE));
        }
        System.out.println("Steam-only author bridge checks passed.");
    }

    private static void verifyHosting(ClassNode hosting) throws Exception {
        BridgePlugin.apply(hosting);
        MethodNode joined = method(hosting, "joined");
        require(calls(joined, BridgePlugin.SERVER, "publishServer") == 1, "one native publication call site");
        require(calls(joined, BridgePlugin.SERVER, "getWorldData") == 1
            && calls(joined, BridgePlugin.WORLD_DATA, "isAllowCommands") == 1,
            "native guest permission is read from the loaded world");
        require(calls(joined, BridgePlugin.PENDING, "upnp") == 0, "old flags cannot select a relay");
        require(calls(joined, BridgePlugin.HOSTING, "relayMod") == 0, "hosting has no relay branch");
        require(calls(joined, BridgePlugin.HOSTING, "lanAddress") == 0, "no automatic LAN address announcement");
        require(hasText(joined, "lanminecraft.hideandhunt.world.open"), "Steam success message retained");
        require(calls(method(hosting, "start"), BridgePlugin.PENDING, "<init>") == 1, "saved world opens");
        for (MethodNode method : hosting.methods) {
            require(calls(method, "de/hideandhunt/client/host/Upnp", "open") == 0, "no router forwarding");
        }
        verifyClass(hosting);
    }

    private static void verifyMenu(ClassNode menu) throws Exception {
        BridgePlugin.apply(menu);
        MethodNode init = method(menu, "init");
        require(calls(init, BridgePlugin.MENU, "refresh") == 1, "manual list refresh retained");
        require(init.instructions.size() == 3, "automatic LAN scan removed from author menu");
        require(calls(method(menu, "refresh"), BridgePlugin.HOSTING, "saved") == 1, "manual addresses loaded");
        require(hasText(method(menu, "draw"), "lanminecraft.hideandhunt.world.steam")
            && !hasText(method(menu, "draw"), "hh.mm.internet")
            && !hasText(method(menu, "draw"), "hh.mm.lan"), "legacy flags do not change world labels");
        verifyClass(menu);
    }

    private static void verifyCreate(ClassNode create) throws Exception {
        BridgePlugin.apply(create);
        require(create.methods.stream().noneMatch(method -> method.name.equals("toggle")), "toggle removed");
        require(!hasText(method(create, "draw"), "hh.cw.upnp"), "toggle label removed");
        require(calls(method(create, "draw"), "de/hideandhunt/client/ui/Widgets", "button") == 2, "form buttons retained");
        require(calls(method(create, "click"), "de/hideandhunt/client/ui/Widgets", "click") == 1, "form input retained");
        require(calls(method(create, "create"), BridgePlugin.HOSTING, "create") == 1, "author world creation retained");
        verifyClass(create);
    }

    private static boolean hasText(MethodNode method, String text) {
        for (var instruction : method.instructions) {
            if (instruction instanceof LdcInsnNode constant && text.equals(constant.cst)) {
                return true;
            }
        }
        return false;
    }

    private static ClassNode read(ZipFile jar, String name) throws Exception {
        try (var stream = jar.getInputStream(jar.getEntry(name + ".class"))) {
            ClassNode node = new ClassNode();
            new ClassReader(stream).accept(node, 0);
            return node;
        }
    }

    private static void verifyClass(ClassNode node) throws Exception {
        for (MethodNode method : node.methods) {
            new Analyzer<>(new BasicVerifier()).analyze(node.name, method);
        }
        var writer = new ClassWriter(0);
        node.accept(writer);
        require(new ClassReader(writer.toByteArray()).getClassName().equals(node.name), "transformed class serializes");
    }

    private static MethodNode method(ClassNode target, String name) {
        return target.methods.stream().filter(method -> method.name.equals(name)).findFirst().orElseThrow();
    }

    private static int calls(MethodNode method, String owner, String name) {
        int count = 0;
        for (var instruction : method.instructions) {
            if (instruction instanceof MethodInsnNode call && call.owner.equals(owner) && call.name.equals(name)) {
                count++;
            }
        }
        return count;
    }

    private static void require(boolean condition, String message) {
        if (!condition) {
            throw new AssertionError(message);
        }
    }
}
